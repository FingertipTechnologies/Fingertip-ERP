"""Variable pay already paid through the VAR_PAY other input becomes the
payslip's own Pay This Month amount, so it still counts towards the annual
target. The input lines go: the input type is removed with this version.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT i.id FROM hr_payslip_input_type i
          JOIN ir_model_data d ON d.res_id = i.id AND d.model = 'hr.payslip.input.type'
         WHERE d.module = 'ft_greythr_migration' AND d.name = 'input_type_variable_pay'
    """)
    row = cr.fetchone()
    if not row:
        return
    cr.execute("""
        UPDATE hr_payslip p
           SET ft_variable_pay_amount = s.amount
          FROM (SELECT payslip_id, SUM(amount) AS amount
                  FROM hr_payslip_input WHERE input_type_id = %s GROUP BY payslip_id) s
         WHERE p.id = s.payslip_id
    """, [row[0]])
    cr.execute("DELETE FROM hr_payslip_input WHERE input_type_id = %s", [row[0]])
