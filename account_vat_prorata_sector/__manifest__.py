# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'VAT Pro Rata Sector',
    'version': '18.0.1.0.0',
    'category': 'Accounting & Finance',
    'license': 'AGPL-3',
    'summary': 'Manages VAT Pro Rata with sectorisation',
    'description': """
VAT Pro Rata Sector
============
This module extend VAT Pro Rata module to work with multiple purchase journals.
The idea is to have 3 purchase journals : 
1 with the invoice for which we deduce all vat
1 with the invoices we can only deduce a prorata of the vat
1 with the invoices we can't deduce anything.
With this module, you will be able to manage 2 misc entry per month to manage the
vat you can't deduce for the 2 last journals
    """,
    'author': 'Akretion',
    'website': 'https://github.com/akretion/odoo-vat-prorata',
    'depends': ['account_vat_pro_rata'],
    'data': [
        "views/account_journal.xml",
        "views/account_vat_prorata.xml",
    ],
    'installable': True,
    'application': True,
}
