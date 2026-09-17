fn supergraph_service(service) {
    service.map_request(|request| {

        let claims = request.context["apollo::authentication::jwt_claims"];
        log_info(`[RHAI] claims = ${claims}`);

        if claims == () {
            request.context["auth_state"]  = "ANONYMOUS";
            request.context["user_id"]     = "";
            request.context["user_role"]   = "";
            request.context["user_email"]  = "";
            request.context["user_pseudo"] = "";
            request.context["user_age"]    = "";
            return;
        }

        request.context["auth_state"] = "VALID";


        request.context["user_id"]     = extract_claim(claims, "sub");
        request.context["user_role"]   = extract_claim(claims, "role");
        request.context["user_email"]  = extract_claim(claims, "email");
        request.context["user_pseudo"] = extract_claim(claims, "pseudo");
        request.context["user_age"]    = extract_claim(claims, "age");
    });
}


fn subgraph_service(service, subgraph) {
    service.map_request(|request| {
        request.subgraph.headers["x-auth-state"]  = read_context(request, "auth_state", "ANONYMOUS");
        request.subgraph.headers["x-user-id"]     = read_context(request, "user_id", "");
        request.subgraph.headers["x-user-role"]   = read_context(request, "user_role", "");
        request.subgraph.headers["x-user-email"]  = read_context(request, "user_email", "");
        request.subgraph.headers["x-user-pseudo"] = read_context(request, "user_pseudo", "");
        request.subgraph.headers["x-user-age"]    = read_context(request, "user_age", "");
    });
}

fn extract_claim(claims, name) {
    let value = ();
    try {
        value = claims[name];
    } catch(err) {
        return "";
    }

    if value == () {
        return "";
    }

    let text = `${value}`;
    text.replace("\r", "");
    text.replace("\n", "");
    return text;
}

fn read_context(request, key, fallback) {
    let value = ();
    try {
        value = request.context[key];
    } catch(err) {
        return fallback;
    }
    if value == () {
        return fallback;
    }
    return value;
}
