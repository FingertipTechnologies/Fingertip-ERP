from . import models


def _ft_fnf_post_init(env):
    """The settlement payslip posts to the same journal as the monthly one, and
    Casual Leave (the company's casual leave type) is paid out at exit."""
    structure = env.ref('ft_full_final_settlement.fnf_structure')
    monthly = env.ref('ft_greythr_migration.greythr_structure')
    for company in env['res.company'].search([]):
        journal = monthly.with_company(company).journal_id
        if journal:
            structure.with_company(company).journal_id = journal
        casual = company.ftp_casual_leave_type_id if 'ftp_casual_leave_type_id' in company._fields else False
        if casual and not company.ft_fnf_encash_leave_type_ids:
            company.ft_fnf_encash_leave_type_ids = casual
