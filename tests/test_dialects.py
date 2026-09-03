import httpx

from refract.dialects import detect


def resp(body, ctype="application/json"):
    return httpx.Response(400, headers={"content-type": ctype}, text=body)


CASES = [
    ("pydantic",
     '{"detail":[{"type":"int_type","loc":["body","age"],"msg":"x"},'
     '{"type":"missing","loc":["body","email"],"msg":"Field required"},'
     '{"type":"enum","loc":["body","role"],"msg":"x","ctx":{"expected":"\'user\', \'admin\'"}}]}',
     {"age": "int", "email": "req", "role": "enum:user,admin"}),

    ("jackson",
     '{"timestamp":"t","status":400,"message":"JSON parse error: Cannot deserialize value of '
     'type `java.lang.Integer` from String: through reference chain: com.x.Account[\\"profile\\"]->com.x.Profile[\\"age\\"]"}',
     {"profile.age": "int"}),

    ("aspnet",
     '{"type":"about:blank","title":"One or more validation errors occurred.","status":400,'
     '"errors":{"Age":["could not be converted to System.Int32. Path: $.age"],'
     '"Email":["The Email field is required."],'
     '"Profile.AvatarUrl":["could not be converted to System.String"]}}',
     {"Age": "int", "Email": "req", "Profile.AvatarUrl": "string"}),

    ("laravel",
     '{"message":"The given data was invalid.","errors":{'
     '"email":["The email field is required."],'
     '"age":["The age must be an integer."],'
     '"profile.avatar":["The profile.avatar field is required."],'
     '"website":["The website must be a valid URL."]}}',
     {"email": "req", "age": "int", "profile.avatar": "req", "website": "url"}),

    ("node-ajv",
     '[{"instancePath":"/age","keyword":"type","params":{"type":"integer"},"message":"must be integer"},'
     '{"instancePath":"","keyword":"required","params":{"missingProperty":"email"},"message":"x"},'
     '{"instancePath":"/role","keyword":"enum","params":{"allowedValues":["user","admin"]},"message":"x"}]',
     {"age": "int", "email": "req", "role": "enum:user,admin"}),

    ("node-joi",
     '{"message":"err","details":[{"message":"\\"age\\" must be a number","path":["age"],"type":"number.base"},'
     '{"message":"x","path":["email"],"type":"any.required"}]}',
     {"age": "float", "email": "req"}),

    ("golang",
     '{"error":"json: cannot unmarshal string into Go struct field Account.age of type int"}',
     {"age": "int"}),

    ("golang-validator",
     "{\"error\":\"Key: 'Account.Email' Error:Field validation for 'Email' failed on the 'required' tag\"}",
     {"email": "req"}),

    ("drf",
     '{"username":["This field is required."],"age":["A valid integer is required."],'
     '"role":["\\"x\\" is not a valid choice."],"profile":{"avatar_url":["This field is required."]}}',
     {"username": "req", "age": "int", "role": "enum", "profile.avatar_url": "req"}),

    ("rails",
     '{"errors":{"name":["can\'t be blank"],"age":["is not a number"]}}',
     {"name": "req", "age": "float"}),
]


def summarize(findings):
    got = {}
    for f in findings:
        key = ".".join(f.path)
        if f.required:
            got[key] = "req"
        elif f.enum:
            got[key] = "enum:" + ",".join(f.enum)
        elif f.type == "enum":
            got[key] = "enum"
        elif f.type:
            got[key] = f.type
    return got


def main():
    ok = True
    for label, body, expect in CASES:
        r = resp(body)
        dialect = detect(r)
        got = summarize(dialect.parse(r))
        problems = []
        for key, want in expect.items():
            if got.get(key) != want:
                problems.append(f"{key}: want {want!r} got {got.get(key)!r}")
        status = "PASS" if not problems else "FAIL"
        if problems:
            ok = False
        print(f"[{status}] {label:18} dialect={dialect.name:9} {got}")
        for p in problems:
            print(f"         {p}")
    print("\nall dialects pass" if ok else "\nsome dialects failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
