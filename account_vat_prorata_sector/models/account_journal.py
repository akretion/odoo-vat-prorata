# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    vat_prorata_type = fields.Selection([
        ('computed', 'Annual Prorata (Calculated)'),
        ('zero', 'Non-Lucrative Sector (0% Recovery)')
    ], string="VAT Prorata Type", help="Used to automate the creation of VAT Pro Rata entries.")
