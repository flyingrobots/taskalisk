//! SHA-256 (FIPS 180-4) as the plan's `artifact_hash` writes it, by the
//! `sha2` crate of the `RustCrypto` project.

use std::fmt::Write as _;

use sha2::{Digest, Sha256};

/// The SHA-256 digest of `data`, as 64 lower-case hexadecimal digits.
#[must_use]
pub fn hex(data: &[u8]) -> String {
    let mut out = String::with_capacity(64);
    for byte in Sha256::digest(data) {
        let _ = write!(out, "{byte:02x}");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::hex;

    /// The call site: the digest written as 1.x writes it (lower-case
    /// hexadecimal, 64 digits), on the FIPS 180-4 examples.
    #[test]
    fn the_fips_180_examples_in_lower_case_hexadecimal() {
        assert_eq!(
            hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
