#include "globals.h"

Action()
{
	web_add_cookie("consent=accepted; DOMAIN=shop.example.com");

	lr_start_transaction("WS_03_Search");

	web_reg_save_param_json("ParamName=first_product_id", "QueryString=$.items[0].id", SEARCH_FILTERS, "Scope=Body", LAST);
	web_reg_save_param_regexp("ParamName=result_count", "RegExp=\"total\":\\s*(\\d+)", "Ordinal=1", SEARCH_FILTERS, "Scope=Body", LAST);
	web_reg_find("Text/IC=\"items\"", LAST);

	web_add_header("X-Requested-With", "XMLHttpRequest");

	web_url("search",
		"URL=https://shop.example.com/api/search?q={SearchTerm}&page=1",
		"Resource=0",
		"RecContentType=application/json",
		"Referer=https://shop.example.com/",
		"Mode=HTTP",
		LAST);

	lr_end_transaction("WS_03_Search", LR_AUTO);

	lr_think_time(5);

	if (atoi(lr_eval_string("{result_count}")) > 0)
	{
		lr_start_transaction("WS_04_Product");

		web_reg_find("Text=Add to cart", LAST);

		web_url("product",
			"URL=https://shop.example.com/product/{first_product_id}",
			"Resource=0",
			"Mode=HTML",
			LAST);

		lr_end_transaction("WS_04_Product", LR_AUTO);
	}
	else
	{
		lr_output_message("No results for %s", lr_eval_string("{SearchTerm}"));
		web_url("no_results",
			"URL=https://shop.example.com/help/no-results",
			"Mode=HTML",
			LAST);
	}

	return 0;
}
