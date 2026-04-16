import frappe


def after_install():
	from rakoli_intergration.custom_fields import setup_custom_fields

	setup_custom_fields()
	frappe.db.commit()


def before_uninstall():
	from rakoli_intergration.custom_fields import delete_rakoli_custom_fields

	delete_rakoli_custom_fields()
	frappe.db.commit()
