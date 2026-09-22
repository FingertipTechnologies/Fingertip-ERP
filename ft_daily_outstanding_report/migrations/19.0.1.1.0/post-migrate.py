def migrate(cr, version):
    # Keep the recipient selected before the Many2many upgrade.
    cr.execute("""
        INSERT INTO ft_outstanding_company_partner_rel (company_id, partner_id)
        SELECT id, daily_outstanding_partner_id FROM res_company
        WHERE daily_outstanding_partner_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
