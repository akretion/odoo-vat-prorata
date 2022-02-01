# Copyright 2017-2022 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vat_prorata = fields.Boolean(related='company_id.vat_prorata', readonly=False)
    vat_prorata_journal_id = fields.Many2one(
        related='company_id.vat_prorata_journal_id', readonly=False,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        )
