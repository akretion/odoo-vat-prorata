# Copyright 2022 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round
from odoo.tools.misc import format_amount, format_date


class L10nFrAccountVatReturn(models.Model):
    _inherit = "l10n.fr.account.vat.return"

    def _get_vat_return_prorata_domain(self):
        self.ensure_one()
        return [
            ("company_id", "=", self.company_id.id),
            ("date_to", "=", self.end_date),
        ]

    def _get_vat_return_prorata(self):
        """Return the VAT prorata of the company that applies to the period
        of the VAT return."""
        self.ensure_one()
        prorata = self.env["account.vat.prorata"].search(
            self._get_vat_return_prorata_domain()
        )
        if not prorata:
            raise UserError(
                _(
                    "There is no VAT prorata in company '{company}' "
                    "for the period that ends on {end_date}."
                ).format(
                    company=self.company_id.display_name,
                    end_date=format_date(self.env, self.end_date),
                )
            )
        if len(prorata) > 1:
            raise UserError(
                _(
                    "There are %(count)s VAT proratas in company '%(company)s' "
                    "for the period that ends on %(end_date)s: %(proratas)s. "
                    "There should be only one: delete the one that doesn't "
                    "apply before generating the VAT return."
                )
                % {
                    "count": len(prorata),
                    "company": self.company_id.display_name,
                    "end_date": format_date(self.env, self.end_date),
                    "proratas": ", ".join(prorata.mapped("display_name")),
                }
            )
        if prorata.state != "done":
            raise UserError(
                _(
                    "You must finish the VAT prorata process in company "
                    "'{company}' for the period that ends on {end_date} "
                    "before doing the VAT return for the same period."
                ).format(
                    company=self.company_id.display_name,
                    end_date=format_date(self.env, self.end_date),
                )
            )
        if prorata.move_id.state != "posted":
            raise UserError(
                _(
                    "The VAT prorata entry of company '{company}' for the "
                    "period that ends on {end_date} is not posted. Post it "
                    "before doing the VAT return, otherwise the deductible "
                    "VAT of the return won't take the prorata into account."
                ).format(
                    company=self.company_id.display_name,
                    end_date=format_date(self.env, self.end_date),
                )
            )
        return prorata

    def _vat_on_payment_prorata_ratio(self, log, prorata):
        """Return the prorata ratio (0 to 100) to apply on the unpaid VAT
        amount of the log. Return 100 to keep the original amount."""
        self.ensure_one()
        return prorata.used_perct

    def _vat_on_payment(self, in_or_out, vat_account_ids, speedy):
        account2logs = super()._vat_on_payment(in_or_out, vat_account_ids, speedy)
        if in_or_out == "in" and self.company_id.vat_prorata:
            prorata = self._get_vat_return_prorata()
            perct_prec = self.env["decimal.precision"].precision_get(
                "VAT Pro Rata Ratio"
            )
            for account, logs in account2logs.items():
                for log in logs:
                    ratio = float_round(
                        self._vat_on_payment_prorata_ratio(log, prorata),
                        precision_digits=perct_prec,
                    )
                    assert float_compare(ratio, 100, precision_digits=perct_prec) <= 0
                    assert float_compare(ratio, 0, precision_digits=perct_prec) >= 0
                    if float_compare(ratio, 100, precision_digits=perct_prec) < 0:
                        log["amount"] *= ratio / 100
                        log["note"] += _(
                            " => VAT prorata ratio {ratio} % "
                            "VAT amount: {vat_amount}"
                        ).format(
                            ratio=ratio,
                            vat_amount=format_amount(
                                self.env, log["amount"], speedy["currency"]
                            ),
                        )
        return account2logs
