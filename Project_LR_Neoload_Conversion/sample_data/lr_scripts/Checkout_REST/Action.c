Action()
{
	int i;
	int rc;

	web_add_auto_header("Content-Type", "application/json");
	web_add_auto_header("Authorization", "Bearer {api_token}");

	lr_start_transaction("CO_01_Cart");

	web_reg_save_param_json("ParamName=cart_id", "QueryString=$.cartId", SEARCH_FILTERS, "Scope=Body", LAST);
	web_reg_find("Text=\"status\":\"OPEN\"", LAST);

	web_custom_request("create_cart",
		"URL=https://api.example.com/v2/carts",
		"Method=POST",
		"Resource=0",
		"RecContentType=application/json",
		"EncType=application/json",
		"Body={\"customer\":\"{CustomerId}\",\"channel\":\"web\"}",
		LAST);

	lr_end_transaction("CO_01_Cart", LR_AUTO);

	for (i = 1; i <= 3; i++)
	{
		lr_save_int(i, "line_no");
		lr_start_transaction("CO_02_AddItem");
		web_custom_request("add_item",
			"URL=https://api.example.com/v2/carts/{cart_id}/items",
			"Method=POST",
			"Body={\"sku\":\"{Sku}\",\"qty\":1,\"line\":{line_no}}",
			LAST);
		lr_end_transaction("CO_02_AddItem", LR_AUTO);
		lr_think_time(2);
	}

	lr_start_transaction("CO_03_Checkout");

	web_reg_save_param("order_id", "LB=\"orderId\":\"", "RB=\"", "NotFound=warning", LAST);

	rc = web_custom_request("checkout",
		"URL=https://api.example.com/v2/carts/{cart_id}/checkout",
		"Method=PUT",
		"Body={\"payment\":\"card\"}",
		LAST);

	if (strcmp(lr_eval_string("{order_id}"), "NOT_FOUND") == 0)
	{
		lr_error_message("Checkout failed for cart %s", lr_eval_string("{cart_id}"));
		lr_end_transaction("CO_03_Checkout", LR_FAIL);
		lr_exit(LR_EXIT_ITERATION_AND_CONTINUE, LR_FAIL);
	}

	lr_end_transaction("CO_03_Checkout", LR_AUTO);

	log_order(lr_eval_string("{order_id}"));

	return 0;
}
