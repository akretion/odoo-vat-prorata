import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo10-addons-akretion-odoo-vat-prorata",
    description="Meta package for akretion-odoo-vat-prorata Odoo addons",
    version=version,
    install_requires=[
        'odoo10-addon-account_vat_pro_rata',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 10.0',
    ]
)
