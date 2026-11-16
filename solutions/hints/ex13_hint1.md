# Ex. 13 — hint 1 (direction)

The endpoint is streaming, but something along the way collects the chunks and hands them over at the end.
Compare two moments: when the application got the first token from the provider and when it sent the first
chunk to the client. In the response generator, look for a list that the chunks go into before anything is
`yield`ed.
