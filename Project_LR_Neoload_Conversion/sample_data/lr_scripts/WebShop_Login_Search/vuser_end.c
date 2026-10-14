vuser_end()
{
	lr_start_transaction("WS_99_Logout");

	web_url("logout",
		"URL=https://shop.example.com/logout?token={csrf_token}",
		"Resource=0",
		"Mode=HTML",
		LAST);

	lr_end_transaction("WS_99_Logout", LR_AUTO);

	return 0;
}
