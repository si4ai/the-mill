/**
 * @name Clear-text logging of sensitive information
 * @description Logging sensitive information without encryption or hashing can
 * expose it to an attacker. Mill treats the redaction helpers as sanitizers.
 * @kind path-problem
 * @problem.severity error
 * @security-severity 7.5
 * @precision high
 * @id mill/clear-text-logging-sensitive-data
 * @tags security
 *       external/cwe/cwe-312
 *       external/cwe/cwe-359
 *       external/cwe/cwe-532
 */

import python
import CleartextLoggingFlow::PathGraph
import semmle.python.security.dataflow.CleartextLoggingQuery
import RedactSecrets

private class RedactSecretsSanitizer extends Sanitizer {
  RedactSecretsSanitizer() { this instanceof RedactSecretsResult }
}

from
  CleartextLoggingFlow::PathNode source, CleartextLoggingFlow::PathNode sink,
  string classification
where
  CleartextLoggingFlow::flowPath(source, sink) and
  classification = source.getNode().(Source).getClassification()
select sink.getNode(), source, sink, "This expression logs $@ as clear text.",
  source.getNode(), "sensitive data (" + classification + ")"
