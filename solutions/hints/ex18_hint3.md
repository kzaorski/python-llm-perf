# Ex. 18 — hint 3 (report skeleton)

For every defect:
```
Symptom:  <what the client sees / which endpoint>
Evidence: <PromQL/TraceQL query or command> = <number from the incident> (expected: <number on the reference state>)
Cause:    <mechanism: e.g. "slots < L = λ·W", "buffer before sending", "no single-flight", "no cancellation">
Fix:      <what to change> ; proof: <probe of exercise NN / check>
```
Plus a "Ruled out" section (with numbers) and an "Interactions" section (which defect amplifies which). Compare
with `solutions/ex18_answers.md`.
