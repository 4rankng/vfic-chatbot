// Compatibility shim. The original Atomic CRM codebase named this file
// `contactModel.ts`. The refactor renamed it to `leadModel.ts`, but several
// older components and the demo data generator still import the old name.
// Re-export everything from the canonical location so both work.
export * from "./leadModel";
