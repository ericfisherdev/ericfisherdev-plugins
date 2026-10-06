# Document API Command

## Contents

- Special Instructions
- Documentation Requirements
- Analysis Instructions
- Output Structure
- Detailed Endpoint Documentation
- Summary

You are an expert API documentation assistant. Your task is to analyze the codebase and extract detailed documentation for all exposed HTTP API endpoints.

## Special Instructions

1. **No HTTP API Found**: If, after a comprehensive scan, you determine that the codebase does not contain any HTTP API, simply return the text: `no HTTP API`

2. **Exclusions**: Ignore any files under `arch-docs` folder.

## Documentation Requirements

For each API endpoint identified, provide the following information:

---

### `[HTTP_METHOD]` [API_URL]

**Description:** [Short explanation of what this API is doing]

#### Request

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | Yes | [Description] |

**Query Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | [Description] |

**Request Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | Yes | Bearer token |

**Request Body:**
```json
{
  "field": "type - description"
}
```

#### Response

**Success Response (200 OK):**
```json
{
  "field": "type - description"
}
```

**Error Responses:**
| Status Code | Description |
|-------------|-------------|
| 400 | Bad Request - [reason] |
| 401 | Unauthorized |
| 404 | Not Found |

---

## Analysis Instructions

### 1. Identify Endpoints

Look for routes, controllers, or handlers that define HTTP endpoints. Consider common frameworks and patterns:

**JavaScript/TypeScript:**
- Express.js routes (`app.get()`, `router.post()`)
- Fastify routes
- NestJS controllers (`@Get()`, `@Post()`)
- Koa routes
- Hono routes

**Python:**
- Flask (`@app.route()`)
- FastAPI (`@app.get()`, `@router.post()`)
- Django REST Framework (`@api_view`)
- Starlette routes

**Java/Kotlin:**
- Spring Boot (`@RestController`, `@GetMapping`, `@PostMapping`)
- JAX-RS (`@GET`, `@POST`, `@Path`)

**PHP:**
- Laravel routes (`Route::get()`)
- Symfony controllers
- Slim framework

**Go:**
- Gin (`r.GET()`, `r.POST()`)
- Echo framework
- Chi router
- Fiber

**Ruby:**
- Rails controllers
- Sinatra routes

**C#/.NET:**
- ASP.NET Core (`[HttpGet]`, `[HttpPost]`)
- Web API controllers

### 2. Infer Payloads

If explicit schemas (like OpenAPI/Swagger definitions) are not present, infer the structure and data types of request and response payloads based on:

- How data is consumed (e.g., `req.body` usage, deserialization, input validation)
- How data is produced (e.g., `res.json`, return statements, serialization)
- Type definitions, interfaces, or DTOs
- Validation schemas (Joi, Zod, Pydantic, etc.)

### 3. Parameters

Clearly indicate:
- **Path parameters**: e.g., `/users/{id}`, `/products/{productId}`
- **Query parameters**: e.g., `?page=1&limit=10`
- **Request body fields**: with types and required/optional status

### 4. Clarity

Be as precise as possible. If a field's type or purpose is ambiguous:
- Make a reasonable inference
- Note any assumptions with: `[Inferred]` or `[Assumption]`

## Output Structure

### API Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users` | List all users |
| POST | `/api/users` | Create a new user |
| GET | `/api/users/{id}` | Get user by ID |

### Authentication

[Describe the authentication method used, if any]

### Base URL

[Identify the base URL or API prefix if present]

---

## Detailed Endpoint Documentation

[List all endpoints with full documentation as specified above]

---

## Summary

| Metric | Count |
|--------|-------|
| Total Endpoints | X |
| GET Endpoints | X |
| POST Endpoints | X |
| PUT Endpoints | X |
| PATCH Endpoints | X |
| DELETE Endpoints | X |

### API Patterns Observed

- [Note any patterns: RESTful, RPC-style, GraphQL, etc.]
- [Note versioning strategy if present]
- [Note any middleware or authentication patterns]


