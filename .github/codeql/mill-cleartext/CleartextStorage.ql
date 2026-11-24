/**
 * @name Clear-text storage of sensitive information
 * @description Sensitive information stored without encryption or hashing can
 * expose it to an attacker. Mill treats the redaction helpers as sanitizers.
 * @kind path-problem
 * @problem.severity error
 * @security-severity 7.5
 * @precision high
 * @id mill/clear-text-storage-sensitive-data
 * @tags security
 *       external/cwe/cwe-312
 *       external/cwe/cwe-315
 *       external/cwe/cwe-359
 */

import python
import CleartextStorageFlow::PathGraph
import semmle.python.security.dataflow.CleartextStorageQuery
import RedactSecrets

private class RedactSecretsSanitizer extends Sanitizer {
  RedactSecretsSanitizer() { this instanceof RedactSecretsResult }
}

/**
 * log_rotate.py only copytruncates a dest_log file that was already passed
 * through redact_secrets. The copy is not a new clear-text store.
 */
private class LogRotateCopy extends Sanitizer {
  LogRotateCopy() {
    this.getLocation().getFile().getRelativePath() = "agent_coord/server/log_rotate.py"
  }
}

from
  CleartextStorageFlow::PathNode source, CleartextStorageFlow::PathNode sink,
  string classification
where
  CleartextStorageFlow::flowPath(source, sink) and
  classification = source.getNode().(Source).getClassification()
select sink.getNode(), source, sink, "This expression stores $@ as clear text.",
  source.getNode(), "sensitive data (" + classification + ")"
