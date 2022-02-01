# Copyright 2017-2022 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class AccountAccount(models.Model):
    _inherit = 'account.account'

    vat_subject = fields.Selection([
        ('vat_subject', 'Income VAT Subject'),
        ('no_vat_subject', 'Income No VAT Subject'),
        ],
        string='Income VAT Subject',
        help="This field is used for VAT pro rata. This field must be "
        "set to 'Income VAT Subject' for all revenue accounts used for "
        "the activity subject to VAT "
        "(including revenue accounts used for the activity suject to VAT "
        "which is excluded from VAT because the fiscal position is Export or "
        "Intra-EU B2B)")
