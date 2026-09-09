import json
import os

import frappe
from frappe.utils import cint, flt, now_datetime

from rakoli_intergration.utils import (
	get_salary_data,
	log_api_call,
	make_error_response,
	make_success_response,
)


# ---------------------------------------------------------------------------
# Swagger / OpenAPI Spec Endpoint
# URL: /api/method/rakoli_intergration.api.get_openapi_spec
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def get_openapi_spec():
	"""Serve the OpenAPI 3.0 JSON spec for the Rakoli integration API."""
	spec_path = os.path.join(os.path.dirname(__file__), "www", "rakoli_api.json")
	with open(spec_path) as f:
		spec = json.load(f)
	return spec


# ---------------------------------------------------------------------------
# API 1 — Fetch Employee Data
@frappe.whitelist()
def get_employee(employee_number=None):
	"""Fetch employee employment and payroll data for Rakoli loan eligibility."""
	if not employee_number:
		response = make_error_response(400, "MISSING_FIELD", "employee_number is required", "employee_number")
		log_api_call("get_employee", "GET", {"employee_number": employee_number}, response, 400)
		return response

	if not frappe.db.exists("Employee", employee_number):
		response = make_error_response(
			404,
			"EMPLOYEE_NOT_FOUND",
			f"No employee found with number {employee_number}",
			"employee_number",
		)
		log_api_call(
			"get_employee",
			"GET",
			{"employee_number": employee_number},
			response,
			404,
			employee=employee_number,
		)
		return response

	employee = frappe.db.get_value(
		"Employee",
		employee_number,
		[
			"name",
			"employee_name",
			"department",
			"company",
			"status",
			"date_of_joining",
			"contract_end_date",
			"bank_name",
			"bank_ac_no",
		],
		as_dict=True,
	)

	# Get employment_type (custom field from HRMS)
	employment_type = frappe.db.get_value("Employee", employee_number, "employment_type") or ""

	if employee.status != "Active":
		response = make_error_response(
			422,
			"EMPLOYEE_NOT_ACTIVE",
			f"Employee {employee_number} has status '{employee.status}'. Only Active employees are eligible.",
			"employment_status",
		)
		response["employment_status"] = employee.status
		log_api_call(
			"get_employee",
			"GET",
			{"employee_number": employee_number},
			response,
			422,
			employee=employee_number,
		)
		return response

	gross_salary, net_salary = get_salary_data(employee_number)

	data = {
		"employee_number": employee.name,
		"full_name": employee.employee_name,
		"department": employee.department,
		"company": employee.company,
		"contract_type": employment_type,
		"contract_start_date": str(employee.date_of_joining) if employee.date_of_joining else None,
		"contract_end_date": str(employee.contract_end_date) if employee.contract_end_date else None,
		"employment_status": employee.status,
		"gross_salary": gross_salary,
		"net_salary": net_salary,
		"bank_name": employee.bank_name,
		"bank_account_number": employee.bank_ac_no,
	}

	response = make_success_response(data)
	log_api_call(
		"get_employee", "GET", {"employee_number": employee_number}, response, 200, employee=employee_number
	)
	return response


# ---------------------------------------------------------------------------
# API 2 — Update Employee Bank Account
@frappe.whitelist()
def update_employee_bank(
	employee_number=None,
	bank_name=None,
	bank_account_number=None,
	updated_at=None,
	updated_by=None,
	reason=None,
):
	"""Update employee bank account in ERPNext (salary rerouting to RMFB)."""
	request_data = {
		"employee_number": employee_number,
		"bank_name": bank_name,
		"bank_account_number": bank_account_number,
		"updated_at": updated_at,
		"updated_by": updated_by,
		"reason": reason,
	}

	# Validate required fields
	if not employee_number or not bank_name or not bank_account_number:
		response = make_error_response(
			400,
			"MISSING_FIELDS",
			"employee_number, bank_name, and bank_account_number are required",
		)
		log_api_call("update_employee_bank", "POST", request_data, response, 400)
		return response

	if not frappe.db.exists("Employee", employee_number):
		response = make_error_response(
			404,
			"EMPLOYEE_NOT_FOUND",
			f"No employee found with number {employee_number}",
			"employee_number",
		)
		log_api_call("update_employee_bank", "POST", request_data, response, 404, employee=employee_number)
		return response

	# Check employee is Active
	status = frappe.db.get_value("Employee", employee_number, "status")
	if status != "Active":
		response = make_error_response(
			422,
			"EMPLOYEE_NOT_ACTIVE",
			f"Employee {employee_number} has status '{status}'. Cannot update bank account.",
			"employment_status",
		)
		log_api_call("update_employee_bank", "POST", request_data, response, 422, employee=employee_number)
		return response

	# Read current bank details before updating
	current = frappe.db.get_value("Employee", employee_number, ["bank_name", "bank_ac_no"], as_dict=True)
	previous_bank_name = current.bank_name or ""
	previous_bank_account = current.bank_ac_no or ""

	# Update bank details
	frappe.db.set_value(
		"Employee",
		employee_number,
		{
			"bank_name": bank_name,
			"bank_ac_no": bank_account_number,
		},
	)

	data = {
		"employee_number": employee_number,
		"previous_bank_name": previous_bank_name,
		"previous_bank_account_number": previous_bank_account,
		"new_bank_name": bank_name,
		"new_bank_account_number": bank_account_number,
		"updated_at": updated_at or str(now_datetime()),
	}

	response = make_success_response(data)
	log_api_call("update_employee_bank", "POST", request_data, response, 200, employee=employee_number)
	return response


# ---------------------------------------------------------------------------
# API 3 — Record Loan in ERPNext
# URL: /api/method/rakoli_intergration.api.record_loan
# ---------------------------------------------------------------------------
@frappe.whitelist()
def record_loan(
	employee_number: str | None = None,
	loan_amount: float | None = None,
	rakoli_loan_id: str | None = None,
	approved_at: str | None = None,
	repayment_start_date: str | None = None,
	instalment_amount: float | None = None,
	instalment_frequency: str | None = None,
	total_instalments: int | None = None,
	loan_status: str | None = None,
):
	"""Record an RMFB-approved loan in ERPNext for employer-side record-keeping."""
	allowed_statuses = ("received", "approved", "active", "paid")
	request_data = {
		"employee_number": employee_number,
		"loan_amount": loan_amount,
		"rakoli_loan_id": rakoli_loan_id,
		"approved_at": approved_at,
		"repayment_start_date": repayment_start_date,
		"instalment_amount": instalment_amount,
		"instalment_frequency": instalment_frequency,
		"total_instalments": total_instalments,
		"loan_status": loan_status,
	}

	# Validate required fields
	if not employee_number or not loan_amount:
		response = make_error_response(
			400,
			"MISSING_FIELDS",
			"employee_number and loan_amount are required",
		)
		log_api_call("record_loan", "POST", request_data, response, 400)
		return response

	if loan_status and loan_status not in allowed_statuses:
		response = make_error_response(
			422,
			"INVALID_STATUS",
			f"loan_status must be one of: {', '.join(allowed_statuses)}",
			"loan_status",
		)
		log_api_call("record_loan", "POST", request_data, response, 422, employee=employee_number)
		return response

	if not frappe.db.exists("Employee", employee_number):
		response = make_error_response(
			404,
			"EMPLOYEE_NOT_FOUND",
			f"No employee found with number {employee_number}",
			"employee_number",
		)
		log_api_call("record_loan", "POST", request_data, response, 404, employee=employee_number)
		return response

	emp_status = frappe.db.get_value("Employee", employee_number, "status")
	if emp_status != "Active":
		response = make_error_response(
			422,
			"EMPLOYEE_NOT_ACTIVE",
			f"Employee {employee_number} has status '{emp_status}'.",
			"employee_number",
		)
		log_api_call("record_loan", "POST", request_data, response, 422, employee=employee_number)
		return response

	# If a Rakoli Loan ID is provided, update that existing record instead of creating a new one.
	existing_loan = (
		frappe.db.get_value(
			"Rakoli Loan",
			rakoli_loan_id,
			[
				"name",
				"employee",
				"loan_amount",
				"loan_status",
				"previous_bank_name",
				"previous_bank_account",
			],
			as_dict=True,
		)
		if rakoli_loan_id
		else None
	)

	if existing_loan:
		updates = {
			"employee": employee_number,
			"loan_amount": flt(loan_amount),
			"instalment_amount": flt(instalment_amount) if instalment_amount is not None else None,
			"instalment_frequency": instalment_frequency or "monthly",
			"total_instalments": cint(total_instalments) if total_instalments is not None else None,
			"loan_status": loan_status or existing_loan.loan_status or "received",
			"approved_at": approved_at,
			"repayment_start_date": repayment_start_date,
		}
		loan_doc = frappe.get_doc("Rakoli Loan", existing_loan.name)
		loan_doc.update({key: value for key, value in updates.items() if value is not None})
		if not loan_doc.previous_bank_name:
			bank_info = frappe.db.get_value(
				"Employee", employee_number, ["bank_name", "bank_ac_no"], as_dict=True
			)
			loan_doc.previous_bank_name = bank_info.bank_name if bank_info else ""
			loan_doc.previous_bank_account = bank_info.bank_ac_no if bank_info else ""
		loan_doc.save(ignore_permissions=True)
		frappe.db.commit()

		data = {
			"rakoli_loan_id": existing_loan.name,
			"erpnext_loan_id": existing_loan.name,
			"employee_number": employee_number,
			"recorded_at": str(now_datetime()),
			"note": "Existing record updated (idempotent)",
		}
		response = make_success_response(data)
		log_api_call(
			"record_loan",
			"POST",
			request_data,
			response,
			200,
			employee=employee_number,
			rakoli_loan=existing_loan.name,
		)
		return response

	try:
		loan = frappe.new_doc("Rakoli Loan")
		bank_info = frappe.db.get_value(
			"Employee", employee_number, ["bank_name", "bank_ac_no"], as_dict=True
		)
		loan.employee = employee_number
		loan.loan_amount = flt(loan_amount)
		loan.instalment_amount = flt(instalment_amount) if instalment_amount is not None else None
		loan.instalment_frequency = instalment_frequency or "monthly"
		loan.total_instalments = cint(total_instalments) if total_instalments is not None else None
		loan.loan_status = loan_status or "received"
		loan.approved_at = approved_at
		loan.repayment_start_date = repayment_start_date
		loan.previous_bank_name = bank_info.bank_name if bank_info else ""
		loan.previous_bank_account = bank_info.bank_ac_no if bank_info else ""
		loan.flags.ignore_permissions = True
		loan.insert()

		frappe.db.commit()

		data = {
			"rakoli_loan_id": loan.name,
			"erpnext_loan_id": loan.name,
			"employee_number": employee_number,
			"recorded_at": str(now_datetime()),
		}
		response = make_success_response(data)
		frappe.local.response["http_status_code"] = 201
		log_api_call(
			"record_loan",
			"POST",
			request_data,
			response,
			201,
			employee=employee_number,
			rakoli_loan=loan.name,
		)
		return response

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(title="Rakoli Record Loan Error")
		response = make_error_response(500, "LOAN_CREATION_FAILED", str(e))
		log_api_call(
			"record_loan",
			"POST",
			request_data,
			response,
			500,
			employee=employee_number,
			error_message=str(e),
		)
		return response


# ---------------------------------------------------------------------------
# API 4 — Check Employee Loan Status
# URL: /api/method/rakoli_intergration.api.check_loan_status
# ---------------------------------------------------------------------------
@frappe.whitelist()
def check_loan_status(employee_number: str | None = None):
	"""Check if an employee has an active Rakoli loan (prevents duplicate loans)."""
	if not employee_number:
		response = make_error_response(400, "MISSING_FIELD", "employee_number is required", "employee_number")
		log_api_call("check_loan_status", "GET", {"employee_number": employee_number}, response, 400)
		return response

	if not frappe.db.exists("Employee", employee_number):
		response = make_error_response(
			404,
			"EMPLOYEE_NOT_FOUND",
			f"No employee found with number {employee_number}",
			"employee_number",
		)
		log_api_call("check_loan_status", "GET", {"employee_number": employee_number}, response, 404)
		return response

	active_loans = frappe.db.get_all(
		"Rakoli Loan",
		filters={
			"employee": employee_number,
			"loan_status": ["!=", "paid"],
		},
		fields=[
			"name",
			"loan_amount",
			"instalment_amount",
			"instalment_frequency",
			"total_instalments",
			"loan_status",
			"approved_at",
			"repayment_start_date",
		],
	)

	if active_loans:
		loans_data = []
		for loan in active_loans:
			loans_data.append(
				{
					"rakoli_loan_id": loan.name,
					"erpnext_loan_id": loan.name,
					"loan_amount": flt(loan.loan_amount),
					"instalment_amount": flt(loan.instalment_amount)
					if loan.instalment_amount is not None
					else None,
					"instalment_frequency": loan.instalment_frequency,
					"total_instalments": cint(loan.total_instalments)
					if loan.total_instalments is not None
					else None,
					"loan_status": loan.loan_status,
					"approved_at": str(loan.approved_at) if loan.approved_at else None,
					"repayment_start_date": str(loan.repayment_start_date)
					if loan.repayment_start_date
					else None,
				}
			)

		data = {
			"employee_number": employee_number,
			"has_active_loan": True,
			"active_loans": loans_data,
		}
	else:
		data = {
			"employee_number": employee_number,
			"has_active_loan": False,
		}

	response = make_success_response(data)
	log_api_call(
		"check_loan_status",
		"GET",
		{"employee_number": employee_number},
		response,
		200,
		employee=employee_number,
	)
	return response


# ---------------------------------------------------------------------------
# API 5 — Update Loan Status
# URL: /api/method/rakoli_intergration.api.update_loan_status
# ---------------------------------------------------------------------------
@frappe.whitelist()
def update_loan_status(
	rakoli_loan_id: str | None = None,
	loan_status: str | None = None,
	updated_at: str | None = None,
	updated_by: str | None = None,
	note: str | None = None,
):
	"""Update the Rakoli loan status as it progresses through its lifecycle."""
	request_data = {
		"rakoli_loan_id": rakoli_loan_id,
		"loan_status": loan_status,
		"updated_at": updated_at,
		"updated_by": updated_by,
		"note": note,
	}

	ALLOWED_STATUSES = ("received", "approved", "active", "paid")

	if not rakoli_loan_id or not loan_status:
		response = make_error_response(
			400,
			"MISSING_FIELDS",
			"rakoli_loan_id and loan_status are required",
		)
		log_api_call("update_loan_status", "POST", request_data, response, 400)
		return response

	if loan_status not in ALLOWED_STATUSES:
		response = make_error_response(
			422,
			"INVALID_STATUS",
			f"loan_status must be one of: {', '.join(ALLOWED_STATUSES)}",
			"loan_status",
		)
		log_api_call("update_loan_status", "POST", request_data, response, 422)
		return response

	loan_data = (
		frappe.db.get_value(
			"Rakoli Loan",
			rakoli_loan_id,
			["name", "employee", "loan_status"],
			as_dict=True,
		)
		if rakoli_loan_id
		else None
	)

	if not loan_data:
		response = make_error_response(
			404,
			"LOAN_NOT_FOUND",
			f"No Rakoli loan found with ID {rakoli_loan_id}",
			"rakoli_loan_id",
		)
		log_api_call("update_loan_status", "POST", request_data, response, 404)
		return response

	previous_status = loan_data.loan_status or ""

	loan_doc = frappe.get_doc("Rakoli Loan", loan_data.name)
	loan_doc.loan_status = loan_status
	if loan_status == "approved" and not loan_doc.approved_at:
		loan_doc.approved_at = updated_at or str(now_datetime())
	loan_doc.save(ignore_permissions=True)

	comment_text = (
		f"Rakoli loan status changed from '{previous_status}' to '{loan_status}'"
		f" by {updated_by or frappe.session.user}."
	)
	if note:
		comment_text += f" Note: {note}"

	loan_doc.add_comment("Info", comment_text)
	frappe.db.commit()

	data = {
		"rakoli_loan_id": loan_data.name,
		"erpnext_loan_id": loan_data.name,
		"employee_number": loan_data.employee,
		"previous_status": previous_status,
		"current_status": loan_status,
		"updated_at": updated_at or str(now_datetime()),
	}

	response = make_success_response(data)
	log_api_call(
		"update_loan_status",
		"POST",
		request_data,
		response,
		200,
		employee=loan_data.employee,
		rakoli_loan=loan_data.name,
	)
	return response
