from refract import graphql as g
from refract.client import _flatten_form


def check(name, got, want):
    ok = got == want
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"   want {want!r}\n   got  {got!r}")
    return ok


def main():
    results = []

    ref = {"kind": "NON_NULL", "ofType": {"kind": "LIST",
           "ofType": {"kind": "OBJECT", "name": "User"}}}
    results.append(check("typeref non-null list", g._typeref(ref), "[User]!"))
    results.append(check("typeref scalar", g._typeref({"kind": "SCALAR", "name": "String"}), "String"))

    errs = [{"message": 'Cannot query field "zz" on type "RootQuery".'}]
    results.append(check("root type", g._root_type(errs), "RootQuery"))

    msg = 'Cannot query field "usr" on type "Query". Did you mean "user" or "users"?'
    suggestions = []
    for s in g._SUGGEST.findall(msg):
        suggestions += g._QUOTED.findall(s)
    results.append(check("did-you-mean harvest", sorted(suggestions), ["user", "users"]))

    args = g._ARG_REQ.findall('Field "user" argument "id" of type "ID!" is required')
    results.append(check("arg extraction", args, [("id", "ID!")]))

    form = _flatten_form({"email": [1], "profile": {"city": "x"}, "tags": ["a", "b"]})
    results.append(check("form flatten", form,
                         {"email": "1", "profile[city]": "x", "tags": "a,b"}))

    print("\nall extras pass" if all(results) else "\nsome extras failed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
