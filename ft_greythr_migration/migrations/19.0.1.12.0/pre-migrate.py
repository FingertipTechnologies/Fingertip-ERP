"""Variable pay moves onto the payslip; the separate Variable Pay records go.

Stop rather than lose an award that was submitted or approved but never paid:
it has to be paid (or cancelled) before upgrading.
"""


def migrate(cr, version):
    cr.execute("SELECT to_regclass('hr_variable_pay')")
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        SELECT name FROM hr_variable_pay
         WHERE state IN ('submitted', 'approved') AND payslip_id IS NULL
    """)
    pending = [row[0] for row in cr.fetchall()]
    if pending:
        raise Exception(
            "Variable Pay records still waiting to be paid: %s. Pay them on a payslip "
            "or reset them to draft before upgrading ft_greythr_migration." % ', '.join(pending))
