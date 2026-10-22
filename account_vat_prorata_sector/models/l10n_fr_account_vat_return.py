# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class L10nFrAccountVatReturn(models.Model):
    _inherit = "l10n.fr.account.vat.return"

    def _get_vat_return_prorata_domain(self):
        # Only the prorata of type 'computed' is used to adjust the
        # deductible VAT of the VAT return: the proratas of type 'zero'
        # are only used to generate the neutralisation entries
        return super()._get_vat_return_prorata_domain() + [
            ("prorata_type", "=", "computed"),
        ]

    def _vat_on_payment_prorata_ratio(self, log, prorata):
        move_id = log.get("origin_move_id")
        if not move_id:
            # Manual line: since not all the purchase journals are
            # pro-ratised, the accountant is expected to enter the amount
            # already taking the prorata into account -> keep it unchanged
            return 100.0
        journal = self.env["account.move"].browse(move_id).journal_id
        if journal.vat_prorata_type == "zero":
            # VAT of a non-deductible sector: already fully neutralised
            # by the VAT prorata entry of type 'zero'
            return 0.0
        if not journal.vat_prorata_type:
            # Sector with a 100% deductible VAT: keep the original amount
            return 100.0
        return prorata.used_perct

    def _generate_deductible_vat(self, speedy):
        self.ensure_one()
        self._check_zero_prorata_entries(speedy)
        return super()._generate_deductible_vat(speedy)

    def _check_zero_prorata_entries(self, speedy):
        """Check that the VAT of the 'zero' sectors of the period has been
        neutralised by a VAT prorata entry of type 'zero'.

        If it is not the case, the VAT of those invoices is still in the
        balance of the deductible VAT accounts and would be deducted in the
        VAT return, whereas it must not be deducted at all.
        """
        self.ensure_one()
        if not self.company_id.vat_prorata:
            return
        zero_journals = self.env["account.journal"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("type", "=", "purchase"),
                ("vat_prorata_type", "=", "zero"),
            ]
        )
        if not zero_journals:
            return
        vat_accounts = self._generate_deductible_vat_prepare_struct(speedy)
        if not vat_accounts:
            return
        period_domain = speedy["base_domain"] + [
            ("date", ">=", self.start_date),
            ("date", "<=", self.end_date),
        ]
        rg_res = self.env["account.move.line"]._read_group(
            period_domain
            + [
                ("journal_id", "in", zero_journals.ids),
                ("account_id", "in", [account.id for account in vat_accounts]),
            ],
            groupby=["journal_id"],
            aggregates=["balance:sum"],
        )
        journals_with_vat = self.env["account.journal"]
        for journal, balance in rg_res:
            if not speedy["currency"].is_zero(balance):
                journals_with_vat |= journal
        if not journals_with_vat:
            return
        proratas = self.env["account.vat.prorata"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("prorata_type", "=", "zero"),
                ("state", "=", "done"),
                ("date_from", "<=", self.end_date),
                ("date_to", ">=", self.end_date),
            ]
        )
        posted_proratas = proratas.filtered(lambda x: x.move_id.state == "posted")
        journals_without_entry = self.env["account.journal"]
        for journal in journals_with_vat:
            if any(journal in x.source_journal_ids for x in posted_proratas):
                continue
            journals_without_entry |= journal
        if journals_without_entry:
            raise UserError(
                _(
                    "The VAT of the non-deductible sector (journal(s) "
                    "%(journals)s) has not been neutralised for the period "
                    "that ends on %(end_date)s: the VAT prorata entry of type "
                    "'zero' is missing or not posted. Generate and post it "
                    "before doing the VAT return, otherwise the "
                    "non-deductible VAT would be deducted in the VAT return."
                )
                % {
                    "journals": ", ".join(
                        sorted(journals_without_entry.mapped("code"))
                    ),
                    "end_date": format_date(self.env, self.end_date),
                }
            )
