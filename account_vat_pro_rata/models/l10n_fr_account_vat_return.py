# Copyright 2022 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, format_amount
from odoo.tools import float_compare, float_round


class L10nFrAccountVatReturn(models.Model):
    _inherit = 'l10n.fr.account.vat.return'

    def _vat_on_payment(self, in_or_out, vat_account_ids, speedy):
        account2logs = super()._vat_on_payment(in_or_out, vat_account_ids, speedy)
        if in_or_out == 'in' and self.company_id.vat_prorata:
            # make sure VAT prorata already exists for that period
            prorata = self.env['account.vat.prorata'].search([
                ('company_id', '=', speedy['company_id']),
                ('date_to', '=', self.end_date)
                ], limit=1)
            if not prorata:
                raise UserError(_(
                    "There is no VAT prorata in company '{company}' "
                    "for the period that ends on {end_date}.").format(
                        company=self.company_id.display_name,
                        end_date=format_date(self.env, self.end_date)))
            if prorata and prorata.state != 'done':
                raise UserError(_(
                    "You must finish the VAT prorata process in company "
                    "'{company}' for the period that ends on {end_date} "
                    "before doing the VAT return for the same period.").format(
                        company=self.company_id.display_name,
                        end_date=format_date(self.env, self.end_date)))
            perct_prec = self.env['decimal.precision'].precision_get(
                'VAT Pro Rata Ratio')
            ratio = float_round(prorata.used_perct, precision_digits=perct_prec)
            assert float_compare(ratio, 100, precision_digits=perct_prec) <= 0
            assert float_compare(ratio, 0, precision_digits=perct_prec) >= 0
            if float_compare(ratio, 100, precision_digits=perct_prec) < 0:
                for account, logs in account2logs.items():
                    for log in logs:
                        log['amount'] *= ratio / 100
                        log['note'] += _(
                            " => VAT prorata ratio {ratio} % "
                            "VAT amount: {vat_amount}").format(
                                ratio=ratio,
                                vat_amount=format_amount(
                                    self.env, log['amount'], speedy["currency"]))
        return account2logs
