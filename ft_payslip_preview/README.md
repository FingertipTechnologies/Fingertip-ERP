# Payslip PDF Preview

Adds a **Preview PDF** button next to **Print** on the payslip form. It opens the
payslip's PDF in a fullscreen dialog inside Odoo, using the browser's own PDF
viewer, so nothing is downloaded. Close the dialog to return to the payslip.

The PDF is rendered by the same report, in the same language and with the same
data as the Print button (`/print/payslips`): the structure's report if one is
set, otherwise the standard payslip report. Only single payslips are previewed;
Print still handles batches.

The preview route `/ft_payslip_preview/<payslip id>` requires the Payroll user
group and read access to the payslip. It streams the PDF with an `inline`
disposition and does not store an attachment.

No existing module is changed. Depends on `hr_payroll` only.

Install:

    ./19venv/bin/python odoo-bin -c community.conf -d DATABASE -i ft_payslip_preview --stop-after-init --no-http

Tests (need an HTTP port, they exercise the route):

    ./19venv/bin/python odoo-bin -c community.conf -d TEST_DATABASE -u ft_payslip_preview --test-enable --test-tags /ft_payslip_preview --stop-after-init --http-port=8029 --max-cron-threads=0
