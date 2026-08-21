//! crustify-audit-scanner — the DETERMINISTIC half.
//!
//! Parses a crate's `.rs` files with `syn` and emits one JSON document
//! describing its unsafe surface. No LLM, no network, no build: parsing only,
//! so it runs against a crate whose C dependencies are not installed — which
//! matters, because the crates most worth auditing (FFI wrappers) are exactly
//! the ones that need system libraries to compile.
//!
//! WHY SYNTAX, NOT TYPES. A rustc driver would be more precise, and a later
//! stage should add one. But the soundness bug this tool was built after —
//! ffmpeg-next's `StreamMut` holding a `&mut Context` and a `&Context` to the
//! same object — is a *syntactic* shape: `transmute_copy` in a constructor,
//! a struct with both reference kinds, a `Deref` impl handing out the shared
//! one. `syn` finds that. Type-level analysis would find more, later.
//!
//! The output is a SEED, never a verdict. It ranks places worth looking; the
//! agent stage explains them and miri decides.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::Serialize;
use syn::{visit::Visit, ImplItem, ReturnType, Type};

#[derive(Serialize, Default)]
struct Counts {
    files: usize,
    code_lines: usize,
    unsafe_blocks: usize,
    unsafe_fns: usize,
    pub_unsafe_fns: usize,
    pub_fns: usize,
    raw_ptr_in_pub_sig: usize,
    transmutes: usize,
    deref_impls: usize,
    deref_mut_impls: usize,
}

#[derive(Serialize)]
struct Site {
    file: String,
    line: usize,
    /// Machine-readable shape tag, e.g. `transmute_copy`, `pub_unsafe_fn`.
    kind: String,
    /// The item this site sits in, for the agent to navigate to.
    item: String,
    /// Why the composer thinks it is worth a look. Never a verdict.
    why: String,
    /// 0-100. Ordering only — the agent re-judges everything.
    suspicion: u8,
}

/// A struct that holds BOTH a shared and an exclusive reference. On its own
/// this is legal and common (the references may point at different things);
/// combined with a `transmute_copy` constructor it is the ffmpeg-next shape.
///
/// Resolved TRANSITIVELY, which is load-bearing. ffmpeg-next's `StreamMut`
/// holds `&mut Context` directly but reaches its shared `&Context` one level
/// down, through a `Stream<'a>` field. A direct-fields-only check misses it —
/// and missing it is missing the bug this tool exists to find.
#[derive(Serialize)]
struct MixedRefStruct {
    file: String,
    line: usize,
    name: String,
    shared_fields: Vec<String>,
    exclusive_fields: Vec<String>,
    /// Fields that reach a reference through another struct rather than
    /// holding one, as `field: Type` — the indirection that hides the shape.
    indirect_fields: Vec<String>,
    /// True when the same file also constructs it via transmute — the
    /// combination that turns a legal struct into an aliasing one.
    transmute_in_file: bool,
}

/// One struct as collected in pass 1, before cross-struct resolution.
struct StructDef {
    file: String,
    line: usize,
    name: String,
    shared: Vec<String>,
    exclusive: Vec<String>,
    /// (field name, named type it holds) for fields whose type is a plain
    /// path — the candidates for transitive resolution in pass 2.
    named: Vec<(String, String)>,
    transmute_in_file: bool,
}

#[derive(Serialize)]
struct Report {
    crate_path: String,
    counts: Counts,
    sites: Vec<Site>,
    mixed_ref_structs: Vec<MixedRefStruct>,
}

struct Scan<'a> {
    file: &'a str,
    src: &'a str,
    counts: Counts,
    sites: Vec<Site>,
    structs: Vec<StructDef>,
    item_stack: Vec<String>,
    /// Inclusive 1-based line ranges of `#[cfg(test)]` items, skipped by the
    /// walk and subtracted from `code_lines`.
    test_spans: Vec<(usize, usize)>,
}

/// True if `attrs` carry a `#[cfg(..)]` naming `test`, including the nested
/// `all(test, ..)` / `any(test, ..)` forms. Matching an IDENT rather than the
/// token text keeps `#[cfg(feature = "test")]` out, where `test` is a string.
fn is_cfg_test(attrs: &[syn::Attribute]) -> bool {
    fn has_test_ident(ts: proc_macro2::TokenStream) -> bool {
        ts.into_iter().any(|t| match t {
            proc_macro2::TokenTree::Ident(i) => i == "test",
            proc_macro2::TokenTree::Group(g) => has_test_ident(g.stream()),
            _ => false,
        })
    }
    attrs.iter().any(|a| {
        a.path().is_ident("cfg")
            && match &a.meta {
                syn::Meta::List(l) => has_test_ident(l.tokens.clone()),
                _ => false,
            }
    })
}

/// The attributes of any item, for the `cfg(test)` test above.
fn item_attrs(i: &syn::Item) -> &[syn::Attribute] {
    use syn::Item::*;
    match i {
        Const(x) => &x.attrs, Enum(x) => &x.attrs, ExternCrate(x) => &x.attrs,
        Fn(x) => &x.attrs, ForeignMod(x) => &x.attrs, Impl(x) => &x.attrs,
        Macro(x) => &x.attrs, Mod(x) => &x.attrs, Static(x) => &x.attrs,
        Struct(x) => &x.attrs, Trait(x) => &x.attrs, TraitAlias(x) => &x.attrs,
        Type(x) => &x.attrs, Union(x) => &x.attrs, Use(x) => &x.attrs,
        _ => &[],
    }
}

fn line_of(src: &str, span: proc_macro2::Span) -> usize {
    let _ = src;
    span.start().line
}

impl<'a> Scan<'a> {
    fn here(&self) -> String {
        if self.item_stack.is_empty() {
            "<file>".into()
        } else {
            self.item_stack.join("::")
        }
    }

    fn push_site(&mut self, line: usize, kind: &str, why: &str, suspicion: u8) {
        let item = self.here();
        self.sites.push(Site {
            file: self.file.to_string(),
            line,
            kind: kind.to_string(),
            item,
            why: why.to_string(),
            suspicion,
        });
    }
}

/// Does this type mention a raw pointer anywhere in its spelling?
fn mentions_raw_ptr(ty: &Type) -> bool {
    let rendered = quote::quote!(#ty).to_string();
    rendered.contains("* const") || rendered.contains("* mut")
}

/// The base identifier of a path type: `Stream<'a>` -> `Stream`,
/// `Option<Foo>` -> `Option`. Used to chase a field into another struct.
fn base_path_name(ty: &Type) -> Option<String> {
    match ty {
        Type::Path(p) => p.path.segments.last().map(|s| s.ident.to_string()),
        _ => None,
    }
}

fn ref_kind(ty: &Type) -> Option<bool> {
    // Some(true) = &mut, Some(false) = &, None = not a reference
    match ty {
        Type::Reference(r) => Some(r.mutability.is_some()),
        _ => None,
    }
}

impl<'ast, 'a> Visit<'ast> for Scan<'a> {
    fn visit_expr_unsafe(&mut self, node: &'ast syn::ExprUnsafe) {
        self.counts.unsafe_blocks += 1;
        syn::visit::visit_expr_unsafe(self, node);
    }

    fn visit_expr_call(&mut self, node: &'ast syn::ExprCall) {
        if let syn::Expr::Path(p) = &*node.func {
            let path = quote::quote!(#p).to_string().replace(' ', "");
            let line = line_of(self.src, node.paren_token.span.join());
            if path.ends_with("transmute_copy") {
                self.counts.transmutes += 1;
                self.push_site(
                    line,
                    "transmute_copy",
                    "duplicates a value past the borrow checker; if the source \
                     is a reference this creates a second reference to the same \
                     object without a reborrow",
                    90,
                );
            } else if path.ends_with("transmute") {
                self.counts.transmutes += 1;
                self.push_site(
                    line,
                    "transmute",
                    "reinterprets a value; on an integer-to-enum transmute an \
                     out-of-range discriminant is immediate UB",
                    70,
                );
            }
        }
        syn::visit::visit_expr_call(self, node);
    }

    fn visit_item(&mut self, node: &'ast syn::Item) {
        // A `#[cfg(test)]` item is not in a normal build, so it is not part of
        // the crate's unsafe surface. Recording its extent lets `code_lines`
        // drop it too, which keeps numerator and denominator over one body of
        // code: an inline `mod tests` otherwise adds its lines to the ratio's
        // bottom and its `unsafe` to the top.
        if is_cfg_test(item_attrs(node)) {
            let sp = syn::spanned::Spanned::span(node);
            self.test_spans.push((sp.start().line, sp.end().line));
            return;
        }
        syn::visit::visit_item(self, node);
    }

    fn visit_item_struct(&mut self, node: &'ast syn::ItemStruct) {
        let mut shared = Vec::new();
        let mut excl = Vec::new();
        for (i, f) in node.fields.iter().enumerate() {
            let nm = f
                .ident
                .as_ref()
                .map(|i| i.to_string())
                .unwrap_or_else(|| i.to_string());
            match ref_kind(&f.ty) {
                Some(true) => excl.push(nm),
                Some(false) => shared.push(nm),
                None => {}
            }
        }
        // Fields whose type is a plain named path: `immutable: Stream<'a>`.
        // Pass 2 asks whether that named type itself reaches a reference.
        let mut named = Vec::new();
        for (i, f) in node.fields.iter().enumerate() {
            if ref_kind(&f.ty).is_some() {
                continue;
            }
            if let Some(base) = base_path_name(&f.ty) {
                let nm = f.ident.as_ref().map(|i| i.to_string())
                    .unwrap_or_else(|| i.to_string());
                named.push((nm, base));
            }
        }
        self.structs.push(StructDef {
            file: self.file.to_string(),
            line: line_of(self.src, node.ident.span()),
            name: node.ident.to_string(),
            shared,
            exclusive: excl,
            named,
            transmute_in_file: self.src.contains("transmute_copy"),
        });
        self.item_stack.push(node.ident.to_string());
        syn::visit::visit_item_struct(self, node);
        self.item_stack.pop();
    }

    fn visit_item_impl(&mut self, node: &'ast syn::ItemImpl) {
        let self_ty = {
            let t = &node.self_ty;
            quote::quote!(#t).to_string().replace(' ', "")
        };
        if let Some((_, path, _)) = &node.trait_ {
            let tr = quote::quote!(#path).to_string().replace(' ', "");
            if tr.ends_with("Deref") {
                self.counts.deref_impls += 1;
                let line = line_of(self.src, node.impl_token.span);
                self.item_stack.push(format!("impl Deref for {self_ty}"));
                self.push_site(
                    line,
                    "deref_impl",
                    "hands out a shared reference derived from this type's \
                     fields; if the type also holds an exclusive reference to \
                     the same object, both are live at once",
                    45,
                );
                self.item_stack.pop();
            }
            if tr.ends_with("DerefMut") {
                self.counts.deref_mut_impls += 1;
                let line = line_of(self.src, node.impl_token.span);
                self.item_stack.push(format!("impl DerefMut for {self_ty}"));
                self.push_site(
                    line,
                    "deref_mut_impl",
                    "exposes the inner value for arbitrary mutation, including \
                     mem::swap and mem::replace, which can break invariants the \
                     wrapper relies on",
                    50,
                );
                self.item_stack.pop();
            }
        }
        self.item_stack.push(format!("impl {self_ty}"));
        for it in &node.items {
            if let ImplItem::Fn(f) = it {
                self.fn_like(
                    &f.sig,
                    matches!(f.vis, syn::Visibility::Public(_)),
                );
            }
        }
        syn::visit::visit_item_impl(self, node);
        self.item_stack.pop();
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        self.fn_like(&node.sig, matches!(node.vis, syn::Visibility::Public(_)));
        self.item_stack.push(node.sig.ident.to_string());
        syn::visit::visit_item_fn(self, node);
        self.item_stack.pop();
    }
}

impl<'a> Scan<'a> {
    fn fn_like(&mut self, sig: &syn::Signature, is_pub: bool) {
        let line = line_of(self.src, sig.ident.span());
        let name = sig.ident.to_string();
        if is_pub {
            self.counts.pub_fns += 1;
        }
        if sig.unsafety.is_some() {
            self.counts.unsafe_fns += 1;
            if is_pub {
                self.counts.pub_unsafe_fns += 1;
                self.item_stack.push(name.clone());
                self.push_site(
                    line,
                    "pub_unsafe_fn",
                    "public API that pushes a safety invariant onto the caller; \
                     each one is a contract the crate's users must uphold and \
                     cannot check",
                    40,
                );
                self.item_stack.pop();
            }
        }
        if !is_pub {
            return;
        }
        let mut raw = sig.inputs.iter().any(|a| match a {
            syn::FnArg::Typed(t) => mentions_raw_ptr(&t.ty),
            _ => false,
        });
        if let ReturnType::Type(_, t) = &sig.output {
            raw |= mentions_raw_ptr(t);
        }
        if raw {
            self.counts.raw_ptr_in_pub_sig += 1;
            self.item_stack.push(name);
            self.push_site(
                line,
                "raw_ptr_in_pub_sig",
                "raw pointer crosses the public API boundary; the safe \
                 alternative is a borrowed handle whose lifetime ties it to \
                 the owner",
                35,
            );
            self.item_stack.pop();
        }
    }
}

fn rs_files(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        for e in rd.flatten() {
            let p = e.path();
            let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
            if p.is_dir() {
                // `target/` is build output; the rest are not the crate's own source.
                if !matches!(name, "target" | ".git" | "tests" | "benches" | "examples") {
                    stack.push(p);
                }
            } else if name.ends_with(".rs") {
                out.push(p);
            }
        }
    }
    out.sort();
    out
}

fn main() {
    let root = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let mut counts = Counts::default();
    let mut sites = Vec::new();
    let mut structs: Vec<StructDef> = Vec::new();

    for path in rs_files(&root) {
        let Ok(src) = std::fs::read_to_string(&path) else { continue };
        let Ok(ast) = syn::parse_file(&src) else { continue };
        let rel = path
            .strip_prefix(&root)
            .unwrap_or(&path)
            .to_string_lossy()
            .to_string();
        counts.files += 1;
        let mut scan = Scan {
            file: &rel,
            src: &src,
            counts: Counts::default(),
            sites: Vec::new(),
            structs: Vec::new(),
            item_stack: Vec::new(),
            test_spans: Vec::new(),
        };
        for item in &ast.items {
            scan.visit_item(item);
        }
        // Counted after the walk, which is what knows where the test items are.
        counts.code_lines += src
            .lines()
            .enumerate()
            .filter(|(i, l)| {
                let ln = i + 1;
                let t = l.trim();
                !t.is_empty()
                    && !t.starts_with("//")
                    && !scan.test_spans.iter().any(|(a, b)| ln >= *a && ln <= *b)
            })
            .count();
        counts.unsafe_blocks += scan.counts.unsafe_blocks;
        counts.unsafe_fns += scan.counts.unsafe_fns;
        counts.pub_unsafe_fns += scan.counts.pub_unsafe_fns;
        counts.pub_fns += scan.counts.pub_fns;
        counts.raw_ptr_in_pub_sig += scan.counts.raw_ptr_in_pub_sig;
        counts.transmutes += scan.counts.transmutes;
        counts.deref_impls += scan.counts.deref_impls;
        counts.deref_mut_impls += scan.counts.deref_mut_impls;
        sites.extend(scan.sites);
        structs.extend(scan.structs);
    }

    // PASS 2 — transitive resolution to a fixpoint.
    //
    // A struct reaches a shared reference if it holds one, or holds a named
    // type that reaches one; likewise exclusive. Iterated rather than
    // recursive so a cyclic type graph terminates (C wrappers have plenty of
    // back-references). Three rounds is well past what real code needs; the
    // loop exits as soon as nothing changes.
    let mut reaches_shared: BTreeMap<String, bool> = BTreeMap::new();
    let mut reaches_excl: BTreeMap<String, bool> = BTreeMap::new();
    for sd in &structs {
        reaches_shared.insert(sd.name.clone(), !sd.shared.is_empty());
        reaches_excl.insert(sd.name.clone(), !sd.exclusive.is_empty());
    }
    for _ in 0..8 {
        let mut changed = false;
        for sd in &structs {
            for (_f, ty) in &sd.named {
                if reaches_shared.get(ty).copied().unwrap_or(false)
                    && !reaches_shared.get(&sd.name).copied().unwrap_or(false)
                {
                    reaches_shared.insert(sd.name.clone(), true);
                    changed = true;
                }
                if reaches_excl.get(ty).copied().unwrap_or(false)
                    && !reaches_excl.get(&sd.name).copied().unwrap_or(false)
                {
                    reaches_excl.insert(sd.name.clone(), true);
                    changed = true;
                }
            }
        }
        if !changed {
            break;
        }
    }

    let mut mixed: Vec<MixedRefStruct> = Vec::new();
    for sd in &structs {
        let sh = !sd.shared.is_empty()
            || sd.named.iter().any(|(_, t)| reaches_shared.get(t).copied().unwrap_or(false));
        let ex = !sd.exclusive.is_empty()
            || sd.named.iter().any(|(_, t)| reaches_excl.get(t).copied().unwrap_or(false));
        if !(sh && ex) {
            continue;
        }
        let indirect = sd
            .named
            .iter()
            .filter(|(_, t)| {
                reaches_shared.get(t).copied().unwrap_or(false)
                    || reaches_excl.get(t).copied().unwrap_or(false)
            })
            .map(|(f, t)| format!("{f}: {t}"))
            .collect();
        mixed.push(MixedRefStruct {
            file: sd.file.clone(),
            line: sd.line,
            name: sd.name.clone(),
            shared_fields: sd.shared.clone(),
            exclusive_fields: sd.exclusive.clone(),
            indirect_fields: indirect,
            transmute_in_file: sd.transmute_in_file,
        });
    }

    // A mixed-ref struct in a file that also transmutes is the ffmpeg-next
    // shape. Promote it to the top of the seed list rather than leaving the
    // agent to notice the correlation itself.
    let hot: BTreeMap<String, String> = mixed
        .iter()
        .filter(|m| m.transmute_in_file)
        .map(|m| (m.file.clone(), m.name.clone()))
        .collect();
    for s in sites.iter_mut() {
        if s.kind == "transmute_copy" && hot.contains_key(&s.file) {
            s.suspicion = 99;
            s.why = format!(
                "{} — and this file declares `{}`, which reaches BOTH a shared \
                 and an exclusive reference. That combination is the aliasing \
                 shape: one `&mut` duplicated into a `&mut` and a `&` to the \
                 same object, both stored and both live.",
                s.why,
                hot.get(&s.file).map(String::as_str).unwrap_or("?")
            );
        }
    }
    sites.sort_by(|a, b| {
        b.suspicion
            .cmp(&a.suspicion)
            .then(a.file.cmp(&b.file))
            .then(a.line.cmp(&b.line))
    });

    let report = Report {
        crate_path: root.to_string_lossy().to_string(),
        counts,
        sites,
        mixed_ref_structs: mixed,
    };
    println!("{}", serde_json::to_string_pretty(&report).unwrap());
}
