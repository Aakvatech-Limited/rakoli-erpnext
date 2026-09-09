"""Context for the Swagger UI page that documents the Rakoli API."""

from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
	context.csrf_token = get_csrf_token()
