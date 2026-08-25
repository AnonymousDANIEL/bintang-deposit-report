# Bintang44 API mapping

Confirmed from the supplied Bintang44 Network captures. No passwords, access tokens, tracking codes, or customer data are stored here.

## Base API

`POST https://90018.gawlt.com/api/v1/index.php`

## Login

Module: `/users/login`

Form fields used:

- `username`
- `password`
- `passcode2fa`
- `trackingCode`
- `captchaOutput`
- `module=/users/login`
- `merchantId=90018`
- `accessId=`
- `accessToken=`

The client accepts common login response token names (`token`, `accessToken`, `access_token`, `authToken`) while using the returned user/access ID.

## Completed deposit totals

Module: `/transactions/getAllTransactions`

Important filters:

- `type=DEPOSIT`
- `status=COMPLETED`
- `sDate=YYYY-MM-DD HH:MM:SS`
- `eDate=YYYY-MM-DD HH:MM:SS`
- `pageIndex=0`
- `includeAdmin=1`
- `background=0`

The report reads only `data.totalCount` and `data.totalAmount`; it does not store transaction/customer rows.

## Daily cross-check / session probe

Module: `/reports/transactions`

Fields:

- `sDate=YYYY-MM-DD`
- `eDate=YYYY-MM-DD`
- `period=Daily`
- `type=ALL`

Deposit totals are read from `data[DATE].DEPOSIT.count` and `data[DATE].DEPOSIT.amount`.
