fn supergraph_service(service) {
    service.map_request(|request| {
        let auth_error = request.context["apollo_authentication::jwt::error"];
        if auth_error != () {
            request.headers["x-auth-state"] = "EXPIRED";
            return;
        }

        let token = "";

        try {
            let auth_header = request.headers["authorization"];
            if auth_header != () && auth_header.starts_with("Bearer ") {
                token = auth_header.sub_string(7);
            }
        } catch(err) {

        }

        if token == "" {
            let cookie_header = ();
            try {
                cookie_header = request.headers["cookie"];
            } catch(err) {
                request.headers["x-auth-state"] = "ANONYMOUS";
                return;
            }

            if cookie_header == () {
                request.headers["x-auth-state"] = "ANONYMOUS";
                return;
            }

            let cookies = cookie_header.split("; ");
            for cookie in cookies {
                if cookie.starts_with("jwt=") {
                    token = cookie.sub_string(4);
                    break;
                }
            }
        }

        if token == "" {
            request.headers["x-auth-state"] = "ANONYMOUS";
            return;
        }

        let segments = token.split(".");

        if segments.len() != 3 {
            request.headers["x-auth-state"] = "INVALID_TOKEN";
            return;
        }

        let b64 = "" + segments[1];
        b64.replace("-", "+");
        b64.replace("_", "/");

        let pad = b64.len() % 4;
        if pad == 2 { b64 += "=="; }
        else if pad == 3 { b64 += "="; }

        let claims = ();
        try {
            let payload = base64::decode(b64);
            claims = json::decode(payload);
        } catch(err) {
            request.headers["x-auth-state"] = "INVALID_TOKEN";
            return;
        }

        if claims == () {
            request.headers["x-auth-state"] = "INVALID_TOKEN";
            return;
        }

        request.headers["x-auth-state"] = "VALID";
        request.headers["x-user-id"] = claims["sub"].to_string();
        request.headers["x-user-role"] = claims["role"].to_string();
        request.headers["x-user-email"] = claims["email"].to_string();
        request.headers["x-user-pseudo"] = claims["pseudo"].to_string();
        request.headers["x-user-age"] = claims["age"].to_string();
    });
}
