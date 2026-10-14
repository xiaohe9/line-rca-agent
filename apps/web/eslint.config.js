import tseslint from "typescript-eslint";

// eslint-plugin-react-hooks is intentionally absent: its flat-config surface changed across
// major versions and has not been verified against ESLint 10 yet. Tracked in the M1
// verification report's "not verified" section rather than added on a guess.
export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "coverage/**"] },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
