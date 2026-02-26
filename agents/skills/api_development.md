# Skill: API Development

## When to Use

Use this skill for tasks that create or modify HTTP endpoints, REST APIs, GraphQL resolvers, or RPC services. This covers route definitions, request handling, validation, error responses, authentication middleware, and API tests.

## Route Design

Follow RESTful conventions for resource-oriented APIs:

| Action | Method | Route | Description |
|--------|--------|-------|-------------|
| List | GET | `/api/v1/users` | Retrieve collection |
| Create | POST | `/api/v1/users` | Create new resource |
| Read | GET | `/api/v1/users/:id` | Retrieve single resource |
| Update | PUT | `/api/v1/users/:id` | Replace entire resource |
| Partial update | PATCH | `/api/v1/users/:id` | Update specific fields |
| Delete | DELETE | `/api/v1/users/:id` | Remove resource |
| Nested | GET | `/api/v1/users/:id/orders` | Related resources |

Conventions:
- Use plural nouns for resource names (`/users`, not `/user`)
- Use kebab-case for multi-word resources (`/order-items`, not `/orderItems`)
- Nest resources only one level deep — deeper nesting suggests a separate top-level resource
- Use query parameters for filtering, sorting, and pagination (`/users?role=admin&sort=created_at`)

## Versioning

Include a version prefix in the URL path:

```
/api/v1/users
/api/v2/users
```

When introducing breaking changes, create a new version. Non-breaking additions (new optional fields, new endpoints) do not require a version bump.

## Request Validation

Validate all input at the API boundary. Never trust client data.

```
# Python (Pydantic) example
class CreateUserRequest(BaseModel):
    email: str = Field(..., pattern=r"^[\w.-]+@[\w.-]+\.\w+$")
    name: str = Field(..., min_length=1, max_length=100)
    role: Literal["admin", "member", "viewer"] = "member"

# TypeScript (Zod) example
const CreateUserSchema = z.object({
  email: z.string().email(),
  name: z.string().min(1).max(100),
  role: z.enum(["admin", "member", "viewer"]).default("member"),
});
```

Validate:
- Required fields are present
- Types are correct (string, number, boolean, array)
- Values are within allowed ranges or sets
- String lengths and formats (email, URL, UUID)
- Array lengths and element types

Return a 400 (Bad Request) with specific field-level errors when validation fails.

## Error Handling

Use a consistent error response format across all endpoints:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {"field": "email", "message": "Invalid email format"},
      {"field": "name", "message": "Name is required"}
    ]
  }
}
```

Map errors to appropriate HTTP status codes:

| Status | When to use |
|--------|------------|
| 400 | Invalid input, validation failure |
| 401 | Missing or invalid authentication |
| 403 | Authenticated but not authorized |
| 404 | Resource not found |
| 409 | Conflict (duplicate, state conflict) |
| 422 | Semantically invalid (syntactically valid but logically wrong) |
| 429 | Rate limit exceeded |
| 500 | Unexpected server error |

Never expose stack traces, internal error messages, or implementation details in error responses. Log them server-side.

## Authentication and Authorization

Implement auth as middleware that runs before route handlers:

```
# Middleware pattern (pseudocode)
function authMiddleware(request, response, next):
    token = extractToken(request.headers.authorization)
    if token is null:
        return response.status(401).json({error: "Authentication required"})

    user = validateToken(token)
    if user is null:
        return response.status(401).json({error: "Invalid token"})

    request.user = user
    next()

# Role-based authorization
function requireRole(roles):
    return function(request, response, next):
        if request.user.role not in roles:
            return response.status(403).json({error: "Insufficient permissions"})
        next()
```

- Extract tokens from the `Authorization` header (`Bearer <token>`)
- Validate tokens on every request — do not cache auth state in the server
- Use middleware for authentication, route-level decorators/guards for authorization
- Return 401 for missing/invalid credentials, 403 for insufficient permissions

## Response Format and Pagination

Use a consistent response envelope: `{"data": ...}` for single resources, `{"data": [...], "pagination": {...}}` for collections. Every list endpoint must support pagination.

**Cursor-based** (preferred for large/changing datasets): `?limit=20&cursor=<token>`
**Offset-based** (simpler, for stable datasets): `?page=2&per_page=20`

Always include pagination metadata (total, next cursor or page). Set a reasonable default and maximum page size (e.g., default 20, max 100).

## Middleware Patterns

Apply cross-cutting concerns as middleware in a consistent order:

1. **Request logging** — log method, path, status, duration
2. **CORS** — configure allowed origins, methods, headers
3. **Rate limiting** — per-client or per-endpoint limits
4. **Authentication** — validate tokens, attach user context
5. **Request parsing** — body parsing, content-type handling
6. **Route handler** — business logic
7. **Error handling** — catch unhandled errors, format response

## Testing APIs

Write integration tests for every endpoint covering: happy path (correct status and body), validation errors (400), auth errors (401/403), not-found (404), and edge cases (empty collections, duplicates). Use the repo's test framework and the framework's test client — do not make real HTTP calls to a running server.

## Anti-Patterns

- **Inconsistent response format**: Every endpoint must use the same envelope structure.
- **Exposing internal errors**: Stack traces and SQL errors in API responses are security risks.
- **Missing validation**: Every field must be validated. "It works in Postman" is not validation.
- **Business logic in route handlers**: Keep handlers thin — validate input, call a service, return the result.
- **Ignoring HTTP semantics**: POST should not be idempotent, PUT should replace, PATCH should partially update.
- **Unpaginated list endpoints**: Any endpoint that returns a collection must support pagination.
- **Hardcoded CORS origins**: Configure allowed origins via environment variables.
- **Auth in each route handler**: Use middleware. Duplicating auth checks is fragile and error-prone.

## Checklist Before Submitting

1. All endpoints follow RESTful naming conventions
2. All input is validated at the boundary with appropriate error messages
3. Error responses use a consistent format with correct HTTP status codes
4. Authentication and authorization are implemented as middleware
5. List endpoints support pagination
6. Integration tests cover happy path, validation errors, auth errors, and not-found cases
7. No stack traces or internal details exposed in error responses
8. API version prefix is present in route paths
