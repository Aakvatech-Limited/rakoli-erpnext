import json

import frappe
from frappe.utils import cint, flt, now_datetime


def get_salary_data(employee_id):
	"""Returns (gross_salary, net_salary) for an employee.

	Waterfall:
	1. Latest submitted Salary Slip -> gross_pay, net_pay
	2. Fallback: latest Salary Structure Assignment -> base as gross, net=None
	"""
	# Try latest submitted Salary Slip first
	salary_slip = frappe.db.get_value(
		"Salary Slip",
		filters={"employee": employee_id, "docstatus": 1},
		fieldname=["gross_pay", "net_pay"],
		order_by="posting_date DESC, creation DESC",
		as_dict=True,
	)
	if salary_slip:
		return flt(salary_slip.gross_pay), flt(salary_slip.net_pay)

	# Fallback to Salary Structure Assignment
	ssa = frappe.db.get_value(
		"Salary Structure Assignment",
		filters={"employee": employee_id, "docstatus": 1},
		fieldname=["base"],
		order_by="from_date DESC",
		as_dict=True,
	)
	if ssa:
		return flt(ssa.base), None

	return None, None


def log_api_call(
	api_endpoint,
	http_method,
	request_data=None,
	response_data=None,
	status_code=200,
	employee=None,
	rakoli_loan=None,
	error_message=None,
):
	"""Creates a Rakoli API Log entry for audit purposes."""
	try:
		log = frappe.new_doc("Rakoli API Log")
		log.api_endpoint = api_endpoint
		log.http_method = http_method
		log.request_data = json.dumps(request_data, default=str) if request_data else None
		log.response_data = json.dumps(response_data, default=str) if response_data else None
		log.status_code = status_code
		if employee and frappe.db.exists("Employee", employee):
			log.employee = employee
		if rakoli_loan and frappe.db.exists("Rakoli Loan", rakoli_loan):
			log.rakoli_loan = rakoli_loan
		log.error_message = error_message
		log.request_by = frappe.session.user
		try:
			log.request_ip = frappe.request.remote_addr if frappe.request else None
		except Exception:
			log.request_ip = None
		log.request_timestamp = now_datetime()
		log.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error("Rakoli API Log Error")


def make_error_response(status_code, error_code, error_message, field=None):
	"""Sets HTTP status code and returns standard Rakoli error response."""
	frappe.local.response["http_status_code"] = status_code
	response = {
		"success": False,
		"error_code": error_code,
		"error_message": error_message,
		"timestamp": str(now_datetime()),
	}
	if field:
		response["field"] = field
	return response


def make_success_response(data):
	"""Returns standard Rakoli success response."""
	return {
		"success": True,
		"data": data,
		"timestamp": str(now_datetime()),
	}
