---
paths:
  - "**/api/**"
  - "**/routes/**"
  - "**/handlers/**"
  - "**/resolvers/**"
  - "**/endpoints/**"
---

# API Design Rules

## REST Conventions
- URLs: plural nouns (`/users`, `/orders`), kebab-case for multi-word
- HTTP methods: GET (read), POST (create), PUT (full replace), PATCH (partial update), DELETE
- Status codes: 200 (ok), 201 (created), 204 (no content), 400 (bad input), 401 (unauthenticated), 403 (forbidden), 404 (not found), 422 (validation error), 500 (server error)

## GraphQL Conventions
- Queries: nouns (`user`, `users`, `orderById`)
- Mutations: verb-noun (`createUser`, `updateOrder`, `deletePayment`)
- Input types: `CreateUserInput`, `UpdateOrderInput`
- Return types: include the mutated object in response
- Error handling: use GraphQL errors with extensions, not null responses

## Response Format
- Consistent envelope: `{ data, error, meta }` or framework default
- Pagination: cursor-based preferred, offset-based acceptable
- Error responses: `{ error: { code, message, details } }`
- Include request ID in error responses for debugging

## Validation
- Validate at the API boundary — reject bad input early
- Use schema validation (Zod, Pydantic, struct tags) not manual checks
- Return specific validation errors per field
- Never trust client input — validate even "impossible" cases

## Authentication
- Use Bearer tokens in Authorization header
- Extract auth in middleware/context, not in individual handlers
- Return 401 for missing/invalid tokens, 403 for insufficient permissions
