<div align="center">

![banner](assets/banner.svg)

![version](https://img.shields.io/badge/version-0.1.0-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.9%2B-blue)

</div>

Refract sends deliberately broken requests at an API and **reads the validation errors it gets back.** Most backends answer a wrong-typed field with that field's real name and expected type, so a handful of malformed requests is usually enough to rebuild the request schema, including fields the client never sends. Then it flags the ones worth attacking.

It works on JSON, form, and query APIs, and has a dedicated mode for GraphQL. It is not a fuzzer or a wordlist guesser, it simply makes the application describe its own input.

## How it works

**The whole trick is one move: send a field the wrong shape, read the complaint.**

Ask most APIs to accept `{"age": []}` and they answer with `age must be an integer`. That one line tells you the field exists and what type it wants. Do that across every field, follow the errors into nested objects, and the schema falls out.

Say your client only ever sends this:

```json
{"username": "bob", "age": 30}
```

Refract turns it into this:

```
schema  (dialect: pydantic, 12 requests)
|-- username: string  required
|-- age: int  required
|-- balance: float  required hidden
|-- org_id: string  required hidden
|-- profile: object  required hidden
|   |-- avatar_url: string  required hidden
|   `-- bio: string  hidden
|-- is_admin: bool  hidden
|-- role: enum  hidden enum{user,staff,admin}
`-- tags: array  hidden

leads  (3)
  [hidden] idor     org_id      identifier field, swap it for another user's value
  [hidden] privesc  is_admin    privilege field, try setting a higher value
  [hidden] privesc  role        enum exposes a privileged value
```

The `hidden` fields are the point: `is_admin`, `role`, and `org_id` never appear in the frontend, but the server accepts them. That is where mass-assignment and access-control bugs live.

Fields with a default value never error on their own, so Refract also names a small set of high-value fields (`role`, `is_admin`, `org_id`, `token`, ...), sends each with the wrong type, and keeps the ones the server complains about. It only trusts a schema when the server's answers change as the input changes, so an endpoint that returns the same response no matter what you send is reported as having no oracle, not invented.

## Install

```
git clone https://github.com/0x127/refract
cd refract
pip install .
```

Or run it in place with just `pip install httpx` and `python -m refract`.

## Usage

Point it at an endpoint. No body needed, the fields are what it finds:

```
refract -u https://api.target.com/v1/account
```

For an endpoint behind a login, give it your session:

```
refract -u https://api.target.com/v1/account --cookie 'session=abc123'
refract -u https://api.target.com/v1/account --bearer eyJhbGciOi...
```

GraphQL is detected automatically. It tries introspection, and if that is off it rebuilds the schema from error messages and "Did you mean" hints, recovering queries, mutations, arguments, and return types:

```
refract -u https://api.target.com/graphql
```

Dont know the endpoints? Point it at the whole site and let it find them from the pages, JS, and OpenAPI spec, then probe each:

```
refract --crawl -u https://app.target.com --delay 0.4
```

Prove a hidden field is really a bug: `--confirm` sets it on your own object, reads the object back, and only reports it if the value actually stuck. It reverts the change when it's done:

```
refract -u https://site.com/api/profile --cookie 'session=...' --confirm
```

Common flags:

```
-u, --url URL          target URL
-r, --request FILE     raw HTTP request file (headers + body)
-d, --data BODY        optional sample JSON body for -u
-H, --header 'K: V'    add a header, repeatable
--cookie 'k=v'         session cookie for authenticated endpoints
--bearer TOKEN         bearer token for authenticated endpoints
--mode M               json | form | query | graphql (default: auto)
--inject               active pass: injection + mass-assignment checks
--confirm              read a field back to prove mass-assignment
--crawl                spider the target and probe every endpoint found
--delay S              wait S seconds between requests
--json / --proto       machine output / protobuf sketch
-o FILE                write to a file
```

## What it reads

It auto-detects the request shape (json, form, query, or graphql) and picks the matching error dialect:

| Dialect | Backend | What it pulls out |
|---|---|---|
| `pydantic` | FastAPI | every field at once, with types, enums, constraints |
| `jackson` | Spring Boot | field paths and types from the deserialization reference chain |
| `aspnet` | .NET ProblemDetails | field names and .NET types |
| `laravel` | PHP / Laravel | dotted field paths and types |
| `drf` | Django REST | nested serializer fields and choices |
| `node` | Ajv and Joi | instance paths, types, enums |
| `golang` | gin and json unmarshal | struct fields and Go types |
| `rails` | Rails | field names and presence |
| `generic` | anything else | `field must be a type` and `field is required` phrasing |

Adding a dialect is one file in `refract/dialects/` with a `matches()` and a `parse()`.

## Output

The default view prints the schema tree, the ranked leads, and a ready-to-send valid request. `--json` gives the same as structured data, `--proto` prints a protobuf sketch.

## About

The idea is not new, it just hasn't been generalized. [req2proto](https://github.com/ddd/req2proto) does this against Google's ProtoJSON APIs and [clairvoyance](https://github.com/nikitastupin/clairvoyance) does it against GraphQL. Refract takes the same error-as-oracle approach, points it at ordinary JSON, form, query, and GraphQL APIs, and adds the part that matters for hunting, turning the recovered schema into a ranked list of fields worth poking.
