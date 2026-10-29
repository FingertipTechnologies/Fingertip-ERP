import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"];
const DONE = {
    applied: "Request sent for approval",
    withdrawn: "Request withdrawn",
    approve: "Approved",
    refuse: "Refused",
};

function parseDate(value) {
    const [y, m, d] = value.split("-").map(Number);
    return new Date(y, m - 1, d);
}

function isoDate(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export class PortalTimeOff extends Interaction {
    static selector = ".o_ft_timeoff_page";

    setup() {
        const data = this.el.dataset;
        this.leaves = JSON.parse(data.calendar || "[]");
        // Odoo numbers working days Monday = 0; JavaScript counts from Sunday.
        this.workingDays = new Set(JSON.parse(data.workingDays || "[0,1,2,3,4]").map((d) => (d + 1) % 7));
        this.today = parseDate(data.today);
        this.month = new Date(this.today.getFullYear(), this.today.getMonth(), 1);
        this.form = this.el.querySelector(".o_ft_apply");
        this.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    start() {
        for (const button of this.el.querySelectorAll(".o_ft_switch button")) {
            this.addListener(button, "click", () => this.showView(button.dataset.view));
        }
        if (this.form) {
            for (const button of this.form.querySelectorAll(".o_ft_types button")) {
                this.addListener(button, "click", () => this.selectType(button));
            }
            for (const button of this.form.querySelectorAll(".o_ft_seg button")) {
                this.addListener(button, "click", () => this.selectPeriod(button));
            }
            for (const name of ["date_from", "date_to"]) {
                this.addListener(this.form.elements[name], "change", () => this.datesChanged(name));
            }
            this.addListener(this.form, "submit", (ev) => this.submit(ev));
            const selected = this.form.querySelector(".o_ft_types button[aria-pressed='true']");
            if (selected) {
                this.selectType(selected);
            }
        }
        for (const button of this.el.querySelectorAll(".o_ft_cal_nav button")) {
            this.addListener(button, "click", () => {
                this.month.setMonth(this.month.getMonth() + Number(button.dataset.month));
                this.renderCalendar();
            });
        }
        for (const button of this.el.querySelectorAll(".o_ft_filters button[data-filter]")) {
            this.addListener(button, "click", () => this.filterOwn(button));
        }
        for (const select of this.el.querySelectorAll("select[data-history]")) {
            this.addListener(select, "change", () => this.filterHistory());
        }
        for (const button of this.el.querySelectorAll("[data-decide]")) {
            this.addListener(button, "click", () => this.decide(button));
        }
        for (const card of this.el.querySelectorAll(".o_ft_bal")) {
            this.tilt(card);
        }
        this.renderCalendar();
        this.waitForAnimationFrame(() => {
            for (const ring of this.el.querySelectorAll(".o_ft_val")) {
                ring.style.strokeDashoffset = 169.65 * (1 - Number(ring.dataset.ring || 0));
            }
        });
        if (this.el.dataset.done && DONE[this.el.dataset.done]) {
            this.toast(DONE[this.el.dataset.done]);
        }
        const url = new URL(window.location.href);
        if (url.searchParams.has("done") || url.searchParams.has("error")) {
            url.searchParams.delete("done");
            url.searchParams.delete("error");
            window.history.replaceState(null, "", url);
        }
    }

    showView(view) {
        for (const button of this.el.querySelectorAll(".o_ft_switch button")) {
            button.setAttribute("aria-pressed", button.dataset.view === view);
        }
        this.el.querySelector(".o_ft_view_me").hidden = view !== "me";
        const team = this.el.querySelector(".o_ft_view_team");
        if (team) {
            team.hidden = view !== "team";
        }
        for (const text of this.el.querySelectorAll("[data-view-text]")) {
            text.hidden = text.dataset.viewText !== view;
        }
        const url = new URL(window.location.href);
        url.searchParams.set("view", view);
        window.history.replaceState(null, "", url);
    }

    // ------------------------------------------------------------------
    // Apply form
    // ------------------------------------------------------------------
    selectType(button) {
        for (const other of this.form.querySelectorAll(".o_ft_types button")) {
            other.setAttribute("aria-pressed", other === button);
        }
        this.form.elements.type_id.value = button.dataset.type;
        const halfDay = button.dataset.half === "1";
        for (const seg of this.form.querySelectorAll(".o_ft_seg")) {
            for (const option of seg.querySelectorAll("button")) {
                option.disabled = !halfDay;
            }
            if (!halfDay) {
                // Full-day types: from the morning of the first day to the end of the last.
                this.setPeriod(seg, seg.dataset.period === "from_period" ? "am" : "pm");
            }
        }
        this.form.querySelector(".o_ft_fullday_note").hidden = halfDay;
        this.refresh();
    }

    selectPeriod(button) {
        this.setPeriod(button.closest(".o_ft_seg"), button.dataset.value);
        this.refresh();
    }

    setPeriod(seg, value) {
        for (const option of seg.querySelectorAll("button")) {
            option.setAttribute("aria-pressed", option.dataset.value === value);
        }
        this.form.elements[seg.dataset.period].value = value;
    }

    datesChanged(name) {
        const from = this.form.elements.date_from;
        const to = this.form.elements.date_to;
        if (name === "date_from" && from.value && (!to.value || to.value < from.value)) {
            to.value = from.value;
        }
        this.refresh();
    }

    refresh() {
        this.previewId = (this.previewId || 0) + 1;
        const id = this.previewId;
        const elements = this.form.elements;
        this.form.querySelector(".o_ft_sum_text").textContent = "Checking…";
        this.waitFor(rpc("/my/time-off/preview", {
            type_id: elements.type_id.value,
            date_from: elements.date_from.value,
            date_to: elements.date_to.value,
            from_period: elements.from_period.value,
            to_period: elements.to_period.value,
        })).then((result) => {
            if (id !== this.previewId) {
                return;
            }
            const error = this.form.querySelector(".o_ft_err");
            this.form.querySelector(".o_ft_sum_text").textContent = result.summary || "—";
            this.form.querySelector(".o_ft_sum_days").textContent = result.days ? result.days_label : "—";
            error.textContent = result.error || "";
            error.hidden = !result.error;
            this.form.querySelector(".o_ft_primary").disabled = Boolean(result.error);
        });
    }

    submit(ev) {
        const button = this.form.querySelector(".o_ft_primary");
        if (button.disabled) {
            ev.preventDefault();
            return;
        }
        button.disabled = true;
        button.textContent = "Sending…";
    }

    // ------------------------------------------------------------------
    // Calendar: left half = morning, right half = afternoon
    // ------------------------------------------------------------------
    marks() {
        const marks = {};
        for (const leave of this.leaves) {
            const end = parseDate(leave.to);
            for (let d = parseDate(leave.from); d <= end; d.setDate(d.getDate() + 1)) {
                if (!this.workingDays.has(d.getDay())) {
                    continue;
                }
                const key = isoDate(d);
                const first = key === leave.from;
                const last = key === leave.to;
                let part = "f";
                if (first && last && leave.fp === leave.tp) {
                    part = leave.fp === "am" ? "l" : "r";
                } else if (first && leave.fp === "pm") {
                    part = "r";
                } else if (last && leave.tp === "am") {
                    part = "l";
                }
                const label = `${leave.type}${part === "l" ? ", morning" : part === "r" ? ", afternoon" : ""}${leave.status === "pending" ? " (waiting)" : ""}`;
                (marks[key] = marks[key] || []).push({ part, label, wait: leave.status === "pending", unpaid: leave.unpaid });
            }
        }
        return marks;
    }

    renderCalendar() {
        const grid = this.el.querySelector(".o_ft_cal");
        if (!grid) {
            return;
        }
        const year = this.month.getFullYear();
        const month = this.month.getMonth();
        this.el.querySelector(".o_ft_cal_title").textContent = `${MONTHS[month]} ${year}`;
        const start = new Date(year, month, 1);
        start.setDate(1 - ((start.getDay() + 6) % 7));
        const marks = this.marks();
        const todayKey = isoDate(this.today);
        grid.replaceChildren();
        for (const name of ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]) {
            const dow = document.createElement("div");
            dow.className = "o_ft_dow";
            dow.textContent = name;
            grid.append(dow);
        }
        for (let i = 0; i < 42; i++) {
            const d = new Date(start);
            d.setDate(start.getDate() + i);
            const key = isoDate(d);
            const list = marks[key] || [];
            const cell = document.createElement("div");
            cell.className = "o_ft_day";
            cell.classList.toggle("o_ft_out", d.getMonth() !== month);
            cell.classList.toggle("o_ft_off", !this.workingDays.has(d.getDay()));
            cell.classList.toggle("o_ft_today", key === todayKey);
            cell.classList.toggle("o_ft_has", list.length > 0);
            if (list.length) {
                cell.title = list.map((m) => m.label).join(", ");
            }
            for (const mark of list) {
                const fill = document.createElement("i");
                fill.className = `o_ft_${mark.part}${mark.wait ? " o_ft_wait" : ""}${mark.unpaid ? " o_ft_lop" : ""}`;
                cell.append(fill);
            }
            const number = document.createElement("span");
            number.textContent = d.getDate();
            cell.append(number);
            grid.append(cell);
        }
    }

    // ------------------------------------------------------------------
    // Lists
    // ------------------------------------------------------------------
    filterOwn(button) {
        const filter = button.dataset.filter;
        for (const other of this.el.querySelectorAll(".o_ft_filters button[data-filter]")) {
            other.setAttribute("aria-pressed", other === button);
        }
        let shown = 0;
        for (const row of this.el.querySelectorAll(".o_ft_list .o_ft_row")) {
            row.hidden = filter !== "all" && row.dataset.status !== filter;
            shown += row.hidden ? 0 : 1;
        }
        this.el.querySelector(".o_ft_list .o_ft_empty").hidden = shown > 0;
    }

    filterHistory() {
        const employee = this.el.querySelector("select[data-history='employee']").value;
        const type = this.el.querySelector("select[data-history='type']").value;
        for (const row of this.el.querySelectorAll(".o_ft_tbl tbody tr[data-employee]")) {
            row.hidden = (employee && row.dataset.employee !== employee) || (type && row.dataset.type !== type);
        }
    }

    // ------------------------------------------------------------------
    // Approve / refuse
    // ------------------------------------------------------------------
    decide(button) {
        const card = button.closest(".o_ft_card3d");
        const refuseBox = card.querySelector(".o_ft_refuse");
        const reason = refuseBox.querySelector("textarea");
        const action = button.dataset.decide;
        if (action === "refuse") {
            refuseBox.hidden = false;
            reason.focus();
            return;
        }
        if (action === "cancel") {
            refuseBox.hidden = true;
            return;
        }
        const decision = action === "approve" ? "approve" : "refuse";
        if (decision === "refuse" && !reason.value.trim()) {
            reason.placeholder = "Write a reason first";
            reason.focus();
            return;
        }
        const error = card.querySelector(".o_ft_err");
        for (const b of card.querySelectorAll("button")) {
            b.disabled = true;
        }
        this.waitFor(rpc(`/my/time-off/${card.dataset.leave}/decide`, {
            decision,
            reason: reason.value,
        })).then(() => {
            const back = card.querySelector(".o_ft_back");
            back.className = `o_ft_back ${decision === "approve" ? "o_ft_ok" : "o_ft_no"}`;
            const title = document.createElement("b");
            title.textContent = decision === "approve" ? "Approved" : "Refused";
            const who = document.createElement("span");
            who.textContent = card.querySelector(".o_ft_req_top h3").textContent;
            back.replaceChildren(title, who);
            card.classList.add("o_ft_flip");
            this.waitForTimeout(() => {
                window.location.assign(`/my/time-off?view=team&done=${decision}`);
            }, this.reduceMotion ? 0 : 1300);
        }).catch((e) => {
            for (const b of card.querySelectorAll("button")) {
                b.disabled = false;
            }
            error.textContent = e.data?.message || e.message || "Could not save. Reload the page and try again.";
            error.hidden = false;
        });
    }

    // ------------------------------------------------------------------
    // Motion
    // ------------------------------------------------------------------
    tilt(card) {
        if (this.reduceMotion) {
            return;
        }
        this.addListener(card, "pointermove", (ev) => {
            const r = card.getBoundingClientRect();
            const x = (ev.clientX - r.left) / r.width - 0.5;
            const y = (ev.clientY - r.top) / r.height - 0.5;
            card.style.transform = `rotateY(${x * 14}deg) rotateX(${-y * 14}deg) translateZ(6px)`;
        });
        this.addListener(card, "pointerleave", () => {
            card.style.transform = "";
        });
    }

    toast(message) {
        const toast = this.el.querySelector(".o_ft_toast");
        const dot = document.createElement("i");
        dot.textContent = "●";
        toast.replaceChildren(dot, document.createTextNode(message));
        toast.classList.add("o_ft_show");
        this.waitForTimeout(() => toast.classList.remove("o_ft_show"), 2800);
    }
}

registry.category("public.interactions").add("ft_portal_time_off.time_off", PortalTimeOff);

// The user menu in the portal bar, on every Fingertip portal page.
export class PortalMenu extends Interaction {
    static selector = ".o_ft_who";

    start() {
        this.button = this.el.querySelector(".o_ft_who_btn");
        this.menu = this.el.querySelector(".o_ft_menu");
        this.addListener(this.button, "click", () => this.toggle(this.menu.hidden));
        this.addListener(document, "click", (ev) => {
            if (!this.el.contains(ev.target)) {
                this.toggle(false);
            }
        });
        this.addListener(document, "keydown", (ev) => ev.key === "Escape" && this.toggle(false));
    }

    toggle(open) {
        this.menu.hidden = !open;
        this.button.setAttribute("aria-expanded", open);
    }
}

registry.category("public.interactions").add("ft_portal_time_off.menu", PortalMenu);

// My account dashboard: balance rings fill in, the two top cards tilt.
export class PortalDashboard extends Interaction {
    static selector = ".o_ft_dash";

    start() {
        this.waitForAnimationFrame(() => {
            for (const ring of this.el.querySelectorAll(".o_ft_val")) {
                ring.style.strokeDashoffset = 169.65 * (1 - Number(ring.dataset.ring || 0));
            }
            // Open the month strip at today when it does not fit.
            const wrap = this.el.querySelector(".o_ft_strip_wrap");
            const today = wrap && wrap.querySelector(".o_ft_sdh.o_ft_stoday");
            const name = wrap && wrap.querySelector(".o_ft_sname");
            if (today && wrap.scrollWidth > wrap.clientWidth) {
                wrap.scrollLeft = Math.max(0, today.offsetLeft - name.offsetWidth - 4 * today.offsetWidth);
            }
        });
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            return;
        }
        for (const card of this.el.querySelectorAll(".o_ft_tilt")) {
            this.addListener(card, "pointermove", (ev) => {
                const r = card.getBoundingClientRect();
                const x = (ev.clientX - r.left) / r.width - 0.5;
                const y = (ev.clientY - r.top) / r.height - 0.5;
                card.style.transform = `rotateY(${x * 6}deg) rotateX(${-y * 6}deg)`;
            });
            this.addListener(card, "pointerleave", () => {
                card.style.transform = "";
            });
        }
    }
}

registry.category("public.interactions").add("ft_portal_time_off.dashboard", PortalDashboard);
