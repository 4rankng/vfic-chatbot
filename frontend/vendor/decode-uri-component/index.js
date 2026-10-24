/**
 * Vendored CommonJS build of decode-uri-component v0.5.1 (CHAT-2).
 *
 * Provenance: https://github.com/SamVerschueren/decode-uri-component/blob/v0.5.1/index.js
 * (npm: decode-uri-component@0.5.1, MIT, Copyright (c) 2017 Sam Verschueren).
 * This file is byte-identical to upstream except for this header, the final
 * export converted from ESM `export default` to CJS `module.exports`, and the
 * two U+FFFD escape literals rendered as the replacement characters themselves
 * (runtime-identical).
 *
 * Why vendored: v0.5.1 is ESM-only (`"type": "module"`), and our
 * query-string@7.1.3 CommonJS build calls `require('decode-uri-component')` and
 * invokes it directly — under the ESM-only package that arrives as a namespace
 * object and every `query-string.parse()` throws `decodeComponent is not a
 * function` (reproduced in list-table pagination tests, 2026-10-24). Upstream
 * publishes no fixed CommonJS release (<=0.4.2 is vulnerable to
 * GHSA-vcc3-ghjq-m6fr; 0.5.0+ is ESM-only), so the patched algorithm ships
 * here as CJS. Behavior through query-string is identical: query-string does
 * its own `+` -> space replacement before calling this decoder.
 */

// Matches one or more consecutive percent-encoded bytes (e.g. `%C3%A5`).
const token = "%[a-f0-9]{2}";
const multiMatcher = new RegExp(`(${token})+`, "gi");

const hexPair = /^[a-f\d]{2}$/i;

// Read a `%XX` sequence at `position`, returning the byte value and where to continue scanning.
function parsePercentByte(input, position) {
  if (input.codePointAt(position) !== 37 || position + 3 > input.length) {
    return;
  }

  const digits = input.slice(position + 1, position + 3);

  if (!hexPair.test(digits)) {
    return;
  }

  return { byte: Number.parseInt(digits, 16), next: position + 3 };
}

/**
 * Return how many bytes a UTF-8 code point needs based on its lead byte.
 * Returns 0 for continuation bytes and other invalid lead bytes.
 */
function utf8SequenceLength(byte) {
  if (byte <= 0x7f) {
    return 1;
  }

  // Start at 0xC2 to exclude overlong 2-byte encodings (0xC0/0xC1).
  if (byte >= 0xc2 && byte <= 0xdf) {
    return 2;
  }

  if (byte >= 0xe0 && byte <= 0xef) {
    return 3;
  }

  if (byte >= 0xf0 && byte <= 0xf4) {
    return 4;
  }

  return 0;
}

function isContinuationByte(byte) {
  return byte >= 0x80 && byte <= 0xbf;
}

/**
 * Decode as much of `input` as possible without throwing.
 *Scans left-to-right in O(n), decoding valid UTF-8 runs and leaving the rest literal.
 */
function decode(input) {
  try {
    return decodeURIComponent(input);
  } catch {
    let output = "";
    let position = 0;

    while (position < input.length) {
      if (input.codePointAt(position) !== 37) {
        output += input.charAt(position);
        position++;
        continue;
      }

      const firstByte = parsePercentByte(input, position);

      // `%` not followed by two hex digits (e.g. `%` or `%G`).
      if (!firstByte) {
        output += input.charAt(position);
        position++;
        continue;
      }

      const sequenceLength = utf8SequenceLength(firstByte.byte);

      // Continuation byte or invalid lead byte — emit one `%XX` literally.
      if (sequenceLength === 0) {
        const pair = input.slice(position, position + 6);

        // UTF-16 BOM byte pairs become two replacement characters.
        if (pair === "%FE%FF" || pair === "%FF%FE") {
          output += "��";
          position += 6;
          continue;
        }

        output += input.slice(position, position + 3);
        position += 3;
        continue;
      }

      let end = firstByte.next;
      let validSequence = true;

      for (let index = 1; index < sequenceLength; index++) {
        const nextByte = parsePercentByte(input, end);

        if (!nextByte || !isContinuationByte(nextByte.byte)) {
          validSequence = false;
          break;
        }

        end = nextByte.next;
      }

      if (validSequence) {
        const encodedSequence = input.slice(position, end);

        try {
          output += decodeURIComponent(encodedSequence);
          position = end;
          continue;
        } catch {
          // Invalid UTF-8 despite correct structure — emit the first byte literally.
        }
      }

      // Missing continuation bytes or decode failure — emit the first byte literally.
      const literal = input.slice(position, position + 3);

      // A truncated `%C2` becomes a replacement character.
      output += literal === "%C2" ? "�" : literal;
      position += 3;
    }

    return output;
  }
}

function customDecodeURIComponent(input) {
  // Decode each percent-encoded run in place in a single pass. Decoded output is never rescanned.
  return input.replace(multiMatcher, (run) => decode(run));
}

module.exports = function decodeUriComponent(encodedURI) {
  if (typeof encodedURI !== "string") {
    throw new TypeError(
      `Expected \`encodedURI\` to be of type \`string\`, got \`${typeof encodedURI}\``,
    );
  }

  try {
    // Try the built in decoder first
    return decodeURIComponent(encodedURI);
  } catch {
    // Fallback to a more advanced decoder
    return customDecodeURIComponent(encodedURI);
  }
};
