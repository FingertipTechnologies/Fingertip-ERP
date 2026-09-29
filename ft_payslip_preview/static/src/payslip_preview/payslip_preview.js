import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";

/**
 * Fullscreen dialog showing a payslip PDF. The browser's own PDF viewer
 * provides zoom, page navigation, print and save, so no buttons are needed.
 */
export class PayslipPreviewDialog extends Component {
    static template = "ft_payslip_preview.PayslipPreviewDialog";
    static components = { Dialog };
    static props = {
        url: String,
        title: String,
        close: Function,
    };
}

registry.category("actions").add("ft_payslip_preview", (env, action) => {
    env.services.dialog.add(PayslipPreviewDialog, {
        url: action.params.url,
        title: action.name,
    });
});
