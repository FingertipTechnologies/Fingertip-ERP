# -*- coding: utf-8 -*-
"""The "Approves Time Off on the Portal" tick became the company's HR for Time Off list."""


def migrate(cr, version):
    cr.execute("""SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'hr_employee' AND column_name = 'ft_portal_time_off_hr'""")
    if not cr.fetchone():
        return
    cr.execute("""INSERT INTO ft_time_off_hr_employee_rel (company_id, employee_id)
                  SELECT company_id, id FROM hr_employee
                  WHERE ft_portal_time_off_hr AND company_id IS NOT NULL
                  ON CONFLICT DO NOTHING""")
    cr.execute("ALTER TABLE hr_employee DROP COLUMN ft_portal_time_off_hr")
