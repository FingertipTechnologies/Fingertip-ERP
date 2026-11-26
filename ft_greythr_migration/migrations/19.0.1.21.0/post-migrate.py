def migrate(cr, version):
    """Gratuity Eligible starts ticked wherever a gratuity is provided today.

    Plain SQL, so no salary is recomputed: the tick only matters from the next
    edit on the Payroll tab.
    """
    cr.execute("UPDATE hr_version SET ft_gratuity_eligible = TRUE WHERE COALESCE(l10n_in_gratuity, 0) > 0")
