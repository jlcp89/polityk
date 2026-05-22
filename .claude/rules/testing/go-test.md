---
paths:
  - "**/*_test.go"
---

# Go Testing Rules

## File Naming
- Tests in same package: `service.go` → `service_test.go`
- Black-box tests in `_test` package for API testing

## Patterns
- Use table-driven tests for multiple input/output scenarios
- Test helpers: `t.Helper()` for clean stack traces
- Use `t.Run()` for subtests in table-driven tests
- Cleanup: use `t.Cleanup()` over `defer` in tests
- Parallel tests: `t.Parallel()` where safe (no shared state)

## Table-Driven Test Template
```go
func TestFunctionName(t *testing.T) {
    tests := []struct {
        name    string
        input   InputType
        want    OutputType
        wantErr bool
    }{
        {name: "valid input", input: ..., want: ..., wantErr: false},
        {name: "empty input", input: ..., want: ..., wantErr: true},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got, err := FunctionName(tt.input)
            if (err != nil) != tt.wantErr {
                t.Errorf("error = %v, wantErr %v", err, tt.wantErr)
                return
            }
            if !reflect.DeepEqual(got, tt.want) {
                t.Errorf("got = %v, want %v", got, tt.want)
            }
        })
    }
}
```

## Assertions
- Use stdlib `testing` package — avoid testify unless project already uses it
- Compare with `reflect.DeepEqual` or `cmp.Diff` (google/go-cmp)
- Test error messages with `errors.Is` and `errors.As`
