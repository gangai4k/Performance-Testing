vuser_init()
{
	web_set_max_html_param_len("4096");
	web_add_auto_header("Accept-Language", "en-US");

	lr_start_transaction("WS_01_Home");

	web_reg_save_param("csrf_token", "LB=name=\"_csrf\" value=\"", "RB=\"", "Ord=1", "Search=Body", LAST);
	web_reg_find("Text=Welcome to WebShop", LAST);

	web_url("home",
		"URL=https://shop.example.com/",
		"Resource=0",
		"RecContentType=text/html",
		"Snapshot=t1.inf",
		"Mode=HTML",
		EXTRARES,
		"Url=/static/app.css", ENDITEM,
		LAST);

	lr_end_transaction("WS_01_Home", LR_AUTO);

	lr_think_time(3);

	lr_start_transaction("WS_02_Login");

	web_reg_save_param_ex("ParamName=session_id", "LB=JSESSIONID=", "RB=;", "Search=Headers", SEARCH_FILTERS, LAST);
	web_reg_find("Text=Invalid credentials", "Fail=Found", LAST);

	web_submit_data("login",
		"Action=https://shop.example.com/login",
		"Method=POST",
		"RecContentType=text/html",
		"Referer=https://shop.example.com/",
		"Mode=HTML",
		ITEMDATA,
		"Name=username", "Value={UserName}", ENDITEM,
		"Name=password", "Value={Password}", ENDITEM,
		"Name=_csrf", "Value={csrf_token}", ENDITEM,
		LAST);

	lr_end_transaction("WS_02_Login", LR_AUTO);

	return 0;
}
