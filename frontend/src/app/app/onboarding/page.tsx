"use client";

import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronRight,
  Coffee,
  Download,
  FileSpreadsheet,
  LoaderCircle,
  Pencil,
  RefreshCcw,
  Sparkles,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { OnboardingProgress } from "@/components/onboarding/onboarding-progress";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useOnboardingPermissions } from "@/hooks/use-onboarding-permissions";
import {
  ApiError,
  api,
  type OnboardingCapabilities,
  type OnboardingImportInspect,
  type OnboardingImportEntity,
  type OnboardingImportResolution,
  type OnboardingImportRun,
  type OnboardingImportRunSummary,
  type OnboardingStatusResponse,
  type OnboardingTemplateOptions,
  type OnboardingTemplateSummary,
  type OnboardingUploadSourceType,
} from "@/lib/api";
import {
  entityCounts,
  entityDisplayName,
  entityPayloadSummary,
  formatBytes,
  GENERIC_IMPORT_COLUMNS,
  genericImportMappingError,
  IMPORT_ENTITY_LABELS,
  IMPORT_STATUS_LABELS,
  initialGenericImportMapping,
  readyProductIds,
  runNeedsInventoryWrite,
} from "@/lib/onboarding";
import { parseMenuPriceToMinor, priceMinorToInput } from "@/lib/menu";

type SetupView = "overview" | "template" | "import" | "run";

const DEFAULT_TEMPLATE_OPTIONS: OnboardingTemplateOptions = {
  sizes: ["250", "350", "450"],
  alternative_milks: ["Oat"],
  extras: ["Extra shot", "Syrups"],
  packaging: true,
  include_draft_recipes: true,
};

export default function SetupPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const permissions = useOnboardingPermissions();
  const [status, setStatus] = useState<OnboardingStatusResponse | null>(null);
  const [capabilities, setCapabilities] = useState<OnboardingCapabilities | null>(null);
  const [templates, setTemplates] = useState<OnboardingTemplateSummary[]>([]);
  const [spreadsheetDownloadUrl, setSpreadsheetDownloadUrl] = useState("");
  const [imports, setImports] = useState<OnboardingImportRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<OnboardingImportRun | null>(null);
  const [view, setView] = useState<SetupView>("overview");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<OnboardingTemplateSummary | null>(null);
  const [templateOptions, setTemplateOptions] = useState(DEFAULT_TEMPLATE_OPTIONS);
  const [uploadSource, setUploadSource] = useState<OnboardingUploadSourceType>("AUTO");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<OnboardingImportInspect | null>(null);
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [targetDrafts, setTargetDrafts] = useState<Record<string, string>>({});
  const [resolutionDrafts, setResolutionDrafts] = useState<Record<string, OnboardingImportResolution>>({});
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, string>>({});
  const [priceDrafts, setPriceDrafts] = useState<Record<string, string>>({});
  const [reviewedRecipes, setReviewedRecipes] = useState<Set<string>>(new Set());
  const [warehouseName, setWarehouseName] = useState("Main Stock");
  const [registerName, setRegisterName] = useState("Main POS");
  const scopeKey = `${currentOrganization?.id ?? ""}:${currentLocation?.id ?? ""}`;
  const scopeRef = useRef(scopeKey);
  const loadRequestRef = useRef(0);
  const operationRequestRef = useRef(0);

  const load = useCallback(async () => {
    if (!accessToken || !currentOrganization || permissions.loading || !permissions.canRead) return;
    const requestId = ++loadRequestRef.current;
    const requestedScope = `${currentOrganization.id}:${currentLocation?.id ?? ""}`;
    setLoading(true);
    setError("");
    try {
      const [nextStatus, nextCapabilities, templateList, importList] = await Promise.all([
        api.getOnboardingStatus(currentOrganization.id, accessToken),
        api.getOnboardingCapabilities(currentOrganization.id, accessToken),
        api.listOnboardingTemplates(currentOrganization.id, accessToken),
        api.listOnboardingImports(currentOrganization.id, accessToken),
      ]);
      if (requestId !== loadRequestRef.current || requestedScope !== scopeRef.current) return;
      setStatus(nextStatus);
      setCapabilities(nextCapabilities);
      setTemplates(templateList.items);
      setSpreadsheetDownloadUrl(templateList.spreadsheet_download_url);
      setImports(importList.items);
      setSelectedRun((current) =>
        current && importList.items.some((item) => item.id === current.id) ? current : null,
      );
    } catch (caught) {
      if (requestId === loadRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, "Setup could not be loaded."));
      }
    } finally {
      if (requestId === loadRequestRef.current && requestedScope === scopeRef.current) setLoading(false);
    }
  }, [accessToken, currentLocation, currentOrganization, permissions.canRead, permissions.loading]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      scopeRef.current = scopeKey;
      loadRequestRef.current += 1;
      operationRequestRef.current += 1;
      setStatus(null);
      setCapabilities(null);
      setTemplates([]);
      setImports([]);
      setSelectedRun(null);
      setTargetDrafts({});
      setResolutionDrafts({});
      setFieldDrafts({});
      setPriceDrafts({});
      setReviewedRecipes(new Set());
      setSelectedTemplate(null);
      setTemplateOptions(DEFAULT_TEMPLATE_OPTIONS);
      setUploadSource("AUTO");
      setUploadFile(null);
      setInspection(null);
      setColumnMapping({});
      setError("");
      setNotice("");
      setView("overview");
      void load();
    });
    return () => {
      cancelled = true;
      loadRequestRef.current += 1;
      operationRequestRef.current += 1;
    };
  }, [load, scopeKey]);

  useEffect(() => {
    void Promise.resolve().then(() => {
      const source = new URLSearchParams(window.location.search).get("source");
      if (source === "template") setView("template");
      if (source === "spreadsheet" || source === "poster" || source === "inventory") {
        setUploadSource(source === "poster" ? "POSTER" : "AUTO");
        setView("import");
      }
    });
  }, []);

  const openRun = useCallback(async (run: OnboardingImportRunSummary) => {
    if (!accessToken || !currentOrganization) return;
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    try {
      const next = await api.getOnboardingImport(run.id, currentOrganization.id, accessToken);
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      setSelectedRun(next);
      seedRunDrafts(next, setPriceDrafts, setFieldDrafts);
      setView("run");
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, "Import could not be opened."));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }, [accessToken, currentOrganization]);

  async function previewTemplate(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !currentLocation || !selectedTemplate || !permissions.canImport) return;
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const run = await api.previewOnboardingTemplate(selectedTemplate.code, {
        client_import_id: crypto.randomUUID(),
        version: selectedTemplate.version,
        location_id: currentLocation.id,
        options: templateOptions,
      }, currentOrganization.id, accessToken);
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      setSelectedRun(run);
      seedRunDrafts(run, setPriceDrafts, setFieldDrafts);
      setImports((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setView("run");
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, "Template preview could not be generated."));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }

  async function bootstrapWorkspace(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !permissions.canWrite) return;
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const result = await api.bootstrapOnboarding({
        warehouse_name: warehouseName.trim(),
        register_name: registerName.trim(),
      }, currentOrganization.id, accessToken);
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      setStatus(result.onboarding);
      const created = [result.created.warehouse ? "warehouse" : "", result.created.register ? "register" : ""].filter(Boolean);
      setNotice(created.length ? `Created ${created.join(" and ")}.` : "Existing warehouse and register reused; no duplicates created.");
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, "Workspace bootstrap could not be completed."));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }

  async function uploadImport(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !currentLocation || !uploadFile || !permissions.canImport) return;
    if (capabilities && uploadFile.size > capabilities.spreadsheet.max_bytes) {
      setError(`Choose a file smaller than ${formatBytes(capabilities.spreadsheet.max_bytes)}.`);
      return;
    }
    if (!inspection) {
      setError("Inspect the file before parsing it.");
      return;
    }
    if (inspection.mapping_required) {
      const mappingError = genericImportMappingError(columnMapping);
      if (mappingError) {
        setError(mappingError);
        return;
      }
    }
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const run = await api.uploadOnboardingImport({
        clientImportId: crypto.randomUUID(),
        locationId: currentLocation.id,
        sourceType: uploadSource,
        file: uploadFile,
        mapping: inspection.mapping_required ? columnMapping : undefined,
      }, currentOrganization.id, accessToken);
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      setSelectedRun(run);
      seedRunDrafts(run, setPriceDrafts, setFieldDrafts);
      setImports((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setView("run");
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, "The file could not be parsed."));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }

  async function inspectImport(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !uploadFile || !permissions.canImport) return;
    if (capabilities && uploadFile.size > capabilities.spreadsheet.max_bytes) {
      setError(`Choose a file smaller than ${formatBytes(capabilities.spreadsheet.max_bytes)}.`);
      return;
    }
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const result = await api.inspectOnboardingImport({
        sourceType: uploadSource,
        file: uploadFile,
      }, currentOrganization.id, accessToken);
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      setInspection(result);
      setColumnMapping(initialGenericImportMapping(result.sheets.flatMap((sheet) => sheet.columns)));
      setNotice(result.mapping_required
        ? "Columns detected. Map the required fields before parsing."
        : `${result.source_type.replaceAll("_", " ").toLowerCase()} format detected.`);
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setInspection(null);
        setColumnMapping({});
        setError(errorMessage(caught, "The file could not be inspected."));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }

  async function updateEntity(entity: OnboardingImportEntity, resolution: OnboardingImportResolution) {
    if (!selectedRun || !accessToken || !currentOrganization || !permissions.canImport) return;
    if (resolution === "MATCH_EXISTING" && !targetDrafts[entity.id]?.trim()) {
      setTargetDrafts((current) => ({ ...current, [entity.id]: current[entity.id] ?? "" }));
      setResolutionDrafts((current) => ({ ...current, [entity.id]: resolution }));
      return;
    }
    await mutateRun(async () => {
      const updated = await api.updateOnboardingImportEntity(selectedRun.id, entity.id, {
        resolution,
        target_id: resolution === "MATCH_EXISTING" ? targetDrafts[entity.id].trim() : null,
      }, currentOrganization.id, accessToken);
      setResolutionDrafts((current) => {
        const next = { ...current };
        delete next[entity.id];
        return next;
      });
      return replaceEntity(selectedRun, updated);
    }, "Resolution could not be saved.");
  }

  async function saveEntityCorrection(entity: OnboardingImportEntity) {
    if (!selectedRun || !accessToken || !currentOrganization || !permissions.canImport) return;
    const field = editableField(entity);
    if (!field) return;
    const value = fieldDrafts[entity.id]?.trim();
    if (!value) {
      setError(`${field.label} cannot be empty.`);
      return;
    }
    await mutateRun(async () => {
      const updated = await api.updateOnboardingImportEntity(selectedRun.id, entity.id, {
        resolution: entity.resolution,
        target_id: entity.target_id,
        payload: { ...entity.payload, [field.key]: value },
      }, currentOrganization.id, accessToken);
      return replaceEntity(selectedRun, updated);
    }, "Correction could not be saved.");
  }

  async function validateRun() {
    if (!selectedRun || !accessToken || !currentOrganization || !permissions.canImport) return;
    await mutateRun(async () => {
      const result = await api.validateOnboardingImport(selectedRun.id, currentOrganization.id, accessToken);
      setNotice(result.valid ? "Validation passed. The import is ready to apply." : "Review the remaining errors before applying.");
      return result.run;
    }, "Import validation failed.");
  }

  async function savePrices() {
    if (!selectedRun || !accessToken || !currentOrganization || !permissions.canImport) return;
    const rows = selectedRun.entities
      .filter((entity) => ["VARIANT", "LOCATION_PRICE"].includes(entity.entity_type) && entity.resolution !== "SKIP")
      .map((entity) => ({ entity_id: entity.id, price_minor: parseMenuPriceToMinor(priceDrafts[entity.id] ?? "") }));
    if (rows.some((row) => row.price_minor === null || BigInt(row.price_minor) > BigInt("9999999999999999"))) {
      setError("Enter a valid non-negative price with no more than two decimal places and within the supported range.");
      return;
    }
    await mutateRun(async () => {
      const result = await api.updateOnboardingPrices(
        selectedRun.id,
        rows.map((row) => ({ entity_id: row.entity_id, price_minor: row.price_minor as string })),
        currentOrganization.id,
        accessToken,
      );
      setNotice("Prices saved and validation refreshed.");
      return result.run;
    }, "Prices could not be saved.");
  }

  async function applyRun() {
    if (!selectedRun || !accessToken || !currentOrganization || !canApply) return;
    await mutateRun(async () => {
      const run = await api.applyOnboardingImport(selectedRun.id, currentOrganization.id, accessToken);
      setNotice("Import applied atomically. Draft products are ready for final review.");
      void load();
      return run;
    }, "Import could not be applied. No partial changes were kept.");
  }

  async function cancelRun() {
    if (!selectedRun || !accessToken || !currentOrganization || !permissions.canImport) return;
    await mutateRun(
      () => api.cancelOnboardingImport(selectedRun.id, currentOrganization.id, accessToken),
      "Import could not be cancelled.",
    );
  }

  async function resumeRun() {
    if (!selectedRun || !accessToken || !currentOrganization || !permissions.canImport) return;
    await mutateRun(
      () => api.resumeOnboardingImport(selectedRun.id, currentOrganization.id, accessToken),
      "Import could not be resumed.",
    );
  }

  async function activateProducts() {
    if (!selectedRun || !accessToken || !currentOrganization || !canApply) return;
    const productIds = readyProductIds(selectedRun);
    const recipes = selectedRun.entities.filter((entity) => entity.entity_type === "RECIPE" && entity.resolution !== "SKIP");
    if (recipes.some((recipe) => !reviewedRecipes.has(recipe.id))) {
      setError("Review every starter recipe before activation.");
      return;
    }
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    try {
      const result = await api.activateReadyOnboardingProducts(selectedRun.id, {
        product_ids: productIds,
        confirm_starter_recipes_reviewed: recipes.length === 0 || recipes.every((recipe) => reviewedRecipes.has(recipe.id)),
      }, currentOrganization.id, accessToken);
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      setNotice(`${result.activated_count} ready ${result.activated_count === 1 ? "product" : "products"} activated.`);
      await load();
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, "Ready products could not be activated."));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }

  async function downloadSpreadsheet() {
    if (!accessToken || !currentOrganization || !spreadsheetDownloadUrl) return;
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    try {
      const blob = await api.downloadOnboardingSpreadsheet(currentOrganization.id, accessToken);
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "beanly-menu-template.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, "Spreadsheet template could not be downloaded."));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }

  async function mutateRun(action: () => Promise<OnboardingImportRun>, fallback: string) {
    const operationId = ++operationRequestRef.current;
    const requestedScope = scopeRef.current;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const run = await action();
      if (operationId !== operationRequestRef.current || requestedScope !== scopeRef.current) return;
      setSelectedRun(run);
      setImports((current) => [run, ...current.filter((item) => item.id !== run.id)]);
    } catch (caught) {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) {
        setError(errorMessage(caught, fallback));
      }
    } finally {
      if (operationId === operationRequestRef.current && requestedScope === scopeRef.current) setWorking(false);
    }
  }

  const canApply = Boolean(
    selectedRun && permissions.canWrite && permissions.canWriteMenu &&
    (!runNeedsInventoryWrite(selectedRun) || permissions.canWriteInventory),
  );
  const activeImports = imports.filter((run) =>
    run.location_id === currentLocation?.id && !["APPLIED", "CANCELLED"].includes(run.status),
  );
  const needsBootstrap = Boolean(status && (
    status.steps.warehouse?.status !== "COMPLETE" || status.steps.register?.status !== "COMPLETE"
  ));

  if (permissions.loading) return <div className="setup-state" aria-live="polite">Checking setup access…</div>;
  if (!permissions.canRead) return <div className="setup-state"><strong>Setup access required</strong><span>Your role cannot view onboarding or imports.</span></div>;
  if (loading) return <div className="setup-state" aria-live="polite">Loading setup…</div>;
  if (error && !status) return <div className="setup-state is-error" role="alert"><strong>Setup could not be loaded</strong><span>{error}</span><button type="button" onClick={() => void load()}>Try again</button></div>;

  return (
    <div className="setup-shell">
      <header className="setup-header">
        <div><p className="setup-eyebrow">Beanly Setup</p><h1>Get ready for your first sale</h1><p>Build a draft menu, review business-specific values, then activate only what is ready.</p></div>
        {status && <span className={status.pos_ready ? "setup-ready is-ready" : "setup-ready"}>{status.pos_ready ? <Check aria-hidden="true" /> : <RefreshCcw aria-hidden="true" />}{status.pos_ready ? "POS ready" : "Setup in progress"}</span>}
      </header>

      {status && <OnboardingProgress status={status} />}
      {error && <div className="setup-banner is-error" role="alert"><AlertTriangle aria-hidden="true" /><span>{error}</span></div>}
      {notice && <div className="setup-banner is-success" role="status"><Check aria-hidden="true" /><span>{notice}</span></div>}

      {view === "overview" && (
        <>
          {status?.status === "COMPLETED" && <section className="setup-complete"><Check aria-hidden="true" /><div><h2>Beanly setup is already complete</h2><p>You can still use imports to update this organization. Imported products always start as drafts.</p></div><Link href="/app/pos">Open POS</Link></section>}
          {needsBootstrap && <form className="setup-bootstrap" onSubmit={bootstrapWorkspace}><div><p className="setup-eyebrow">Business basics</p><h2>Create the first stock and POS points</h2><p>This idempotent step reuses existing resources and never creates duplicate defaults.</p></div><label><span>Warehouse name</span><input required maxLength={150} value={warehouseName} onChange={(event) => setWarehouseName(event.target.value)} /></label><label><span>Register name</span><input required maxLength={150} value={registerName} onChange={(event) => setRegisterName(event.target.value)} /></label><button className="setup-primary" type="submit" disabled={working || !permissions.canWrite}>{working ? <LoaderCircle className="is-spinning" /> : <Check />}{permissions.canWrite ? "Prepare workspace" : "Write access required"}</button></form>}
          {activeImports.length > 0 && <section className="setup-resume"><div className="setup-section-heading"><div><p className="setup-eyebrow">Resume</p><h2>Continue an import</h2></div><span>{activeImports.length} in progress</span></div><div className="setup-run-list">{activeImports.map((run) => <button type="button" key={run.id} onClick={() => void openRun(run)}><span><strong>{run.source_name}</strong><small>{run.entity_count} entities · {run.error_count} errors · {run.warning_count} warnings · {IMPORT_STATUS_LABELS[run.status]}</small></span><ChevronRight aria-hidden="true" /></button>)}</div></section>}
          <section className="setup-start"><div className="setup-section-heading"><div><p className="setup-eyebrow">Menu</p><h2>How do you want to create your menu?</h2><p>Nothing is written to the live menu until you review and apply an import.</p></div></div><div className="setup-choice-grid">
            <Choice icon={<Coffee />} title="Beanly template" copy="Start with a versioned coffee-shop menu and optional draft recipes." disabled={!permissions.canImport} onClick={() => setView("template")} />
            <Choice icon={<FileSpreadsheet />} title="Excel / CSV / Poster" copy="Inspect columns, map unfamiliar headers, then review every entity and match explicitly." disabled={!permissions.canImport} onClick={() => setView("import")} />
            <Choice icon={<Sparkles />} title="AI Menu Import" copy={capabilities?.ai.available ? "Extract menu facts from a photo or PDF, then review every field." : "Unavailable — no extraction provider is configured."} disabled={!permissions.canImport || !capabilities?.ai.available} badge={capabilities?.ai.available ? "Review required" : "Unavailable"} />
            <Link className="setup-choice" href="/app/menu/products/new"><span className="setup-choice-icon"><Pencil aria-hidden="true" /></span><span><strong>Create manually</strong><small>Add products one at a time in Menu.</small></span><ChevronRight aria-hidden="true" /></Link>
          </div></section>
          <section className="setup-safety"><AlertTriangle aria-hidden="true" /><div><strong>Fiscal readiness is separate</strong><p>You can finish menu and inventory setup while live provider verification is incomplete. Locations in LIVE_REQUIRED mode are not marked POS ready until fiscal checks pass.</p></div><Link href="/app/settings/fiscal">Review fiscal setup</Link></section>
        </>
      )}

      {view === "template" && <TemplateView templates={templates} selected={selectedTemplate} options={templateOptions} disabled={!permissions.canImport || working} onBack={() => setView("overview")} onSelect={setSelectedTemplate} onOptions={setTemplateOptions} onSubmit={previewTemplate} />}
      {view === "import" && <ImportView capabilities={capabilities} source={uploadSource} file={uploadFile} inspection={inspection} mapping={columnMapping} disabled={!permissions.canImport || working} onBack={() => setView("overview")} onSource={(source) => { setUploadSource(source); setInspection(null); setColumnMapping({}); }} onFile={(file) => { setUploadFile(file); setInspection(null); setColumnMapping({}); }} onMapping={(source, target) => setColumnMapping((current) => { const next = { ...current }; if (target) next[source] = target; else delete next[source]; return next; })} onSubmit={inspection ? uploadImport : inspectImport} onDownload={() => void downloadSpreadsheet()} />}
      {view === "run" && selectedRun && <RunView run={selectedRun} currency={currentOrganization?.currency_code ?? "KZT"} working={working} canImport={permissions.canImport} canApply={canApply} targetDrafts={targetDrafts} resolutionDrafts={resolutionDrafts} fieldDrafts={fieldDrafts} priceDrafts={priceDrafts} reviewedRecipes={reviewedRecipes} onBack={() => { setView("overview"); setSelectedRun(null); }} onTargetDraft={(id, value) => setTargetDrafts((current) => ({ ...current, [id]: value }))} onFieldDraft={(id, value) => setFieldDrafts((current) => ({ ...current, [id]: value }))} onPriceDraft={(id, value) => setPriceDrafts((current) => ({ ...current, [id]: value }))} onReviewRecipe={(id, checked) => setReviewedRecipes((current) => { const next = new Set(current); if (checked) next.add(id); else next.delete(id); return next; })} onResolution={(entity, resolution) => void updateEntity(entity, resolution)} onSaveCorrection={(entity) => void saveEntityCorrection(entity)} onValidate={() => void validateRun()} onSavePrices={() => void savePrices()} onApply={() => void applyRun()} onCancel={() => void cancelRun()} onResume={() => void resumeRun()} onActivate={() => void activateProducts()} />}
    </div>
  );
}

function Choice({ icon, title, copy, badge, disabled, onClick }: { icon: React.ReactNode; title: string; copy: string; badge?: string; disabled?: boolean; onClick?: () => void }) {
  return <button className="setup-choice" disabled={disabled} type="button" onClick={onClick}><span className="setup-choice-icon" aria-hidden="true">{icon}</span><span><strong>{title}{badge && <em>{badge}</em>}</strong><small>{copy}</small></span><ChevronRight aria-hidden="true" /></button>;
}

function TemplateView({ templates, selected, options, disabled, onBack, onSelect, onOptions, onSubmit }: { templates: OnboardingTemplateSummary[]; selected: OnboardingTemplateSummary | null; options: OnboardingTemplateOptions; disabled: boolean; onBack: () => void; onSelect: (template: OnboardingTemplateSummary) => void; onOptions: (options: OnboardingTemplateOptions) => void; onSubmit: (event: FormEvent) => void }) {
  return <form className="setup-panel" onSubmit={onSubmit}><button className="setup-back" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" />Setup choices</button><div className="setup-section-heading"><div><p className="setup-eyebrow">Starter menu</p><h2>Choose a coffee shop template</h2><p>Templates create draft products. You decide the prices, recipes, and activation.</p></div></div><div className="setup-template-grid">{templates.map((template) => <label className={selected?.code === template.code ? "is-selected" : ""} key={`${template.code}:${template.version}`}><input type="radio" name="template" checked={selected?.code === template.code} onChange={() => onSelect(template)} /><span><Coffee aria-hidden="true" /><strong>{template.name}</strong><small>{template.description}</small><em>{template.category_count} categories · {template.product_count} products · v{template.version}</em></span></label>)}</div>{selected && <fieldset className="setup-options"><legend>Configure {selected.name}</legend><OptionChecks label="Sizes" values={["250", "350", "450"]} selected={options.sizes} onChange={(sizes) => onOptions({ ...options, sizes })} /><OptionChecks label="Alternative milk" values={["Oat", "Almond", "Coconut"]} selected={options.alternative_milks} onChange={(alternative_milks) => onOptions({ ...options, alternative_milks })} /><OptionChecks label="Extras" values={["Extra shot", "Syrups"]} selected={options.extras} onChange={(extras) => onOptions({ ...options, extras })} /><label className="setup-check"><input type="checkbox" checked={options.packaging} onChange={(event) => onOptions({ ...options, packaging: event.target.checked })} /><span><strong>Include cups and lids</strong><small>Packaging inventory is added to the draft.</small></span></label><label className="setup-check"><input type="checkbox" checked={options.include_draft_recipes} onChange={(event) => onOptions({ ...options, include_draft_recipes: event.target.checked })} /><span><strong>Create starter recipes</strong><small>Starter values require operator review before activation.</small></span></label></fieldset>}<div className="setup-warning"><AlertTriangle aria-hidden="true" /><span><strong>Starter recipes are starting values, not preparation instructions.</strong> Review doses, yields, milk quantities, cups, and lids for your coffee shop.</span></div><div className="setup-actions"><button className="setup-secondary" type="button" onClick={onBack}>Cancel</button><button className="setup-primary" type="submit" disabled={disabled || !selected || options.sizes.length === 0}>{disabled ? <LoaderCircle className="is-spinning" /> : <Coffee />}Generate preview</button></div></form>;
}

function OptionChecks({ label, values, selected, onChange }: { label: string; values: string[]; selected: string[]; onChange: (values: string[]) => void }) {
  return <div className="setup-option-row"><strong>{label}</strong><div>{values.map((value) => <label key={value}><input type="checkbox" checked={selected.includes(value)} onChange={(event) => onChange(event.target.checked ? [...selected, value] : selected.filter((item) => item !== value))} />{value}</label>)}</div></div>;
}

function ImportView({ capabilities, source, file, inspection, mapping, disabled, onBack, onSource, onFile, onMapping, onSubmit, onDownload }: { capabilities: OnboardingCapabilities | null; source: OnboardingUploadSourceType; file: File | null; inspection: OnboardingImportInspect | null; mapping: Record<string, string>; disabled: boolean; onBack: () => void; onSource: (source: OnboardingUploadSourceType) => void; onFile: (file: File | null) => void; onMapping: (source: string, target: string) => void; onSubmit: (event: FormEvent) => void; onDownload: () => void }) {
  const posterExtensions = capabilities?.poster.extensions ?? [".xls", ".xlsx"];
  const accepted = source === "POSTER" ? posterExtensions.join(",") : ".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv";
  const formats = source === "POSTER" ? posterExtensions.join(" or ") : ".xlsx or .csv";
  const columns = inspection ? [...new Set(inspection.sheets.flatMap((sheet) => sheet.columns))] : [];
  const selectedTargets = Object.values(mapping);
  const mappingReady = !inspection?.mapping_required || genericImportMappingError(mapping) === null;
  return <form className="setup-panel" onSubmit={onSubmit}><button className="setup-back" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" />Setup choices</button><div className="setup-section-heading"><div><p className="setup-eyebrow">Spreadsheet import</p><h2>Upload a menu or inventory file</h2><p>The file is inspected without creating an ImportRun. Business data stays unchanged until final apply.</p></div><button className="setup-download" type="button" onClick={onDownload}><Download aria-hidden="true" />Beanly XLSX template</button></div><fieldset className="setup-source"><legend>File format</legend><label><input type="radio" name="source" checked={source === "AUTO"} onChange={() => onSource("AUTO")} /><span><strong>Excel / CSV</strong><small>Beanly files are detected directly; unfamiliar columns open the mapping step.</small></span></label><label><input type="radio" name="source" checked={source === "POSTER"} onChange={() => onSource("POSTER")} disabled={!capabilities?.poster.available} /><span><strong>Poster export</strong><small>Uses the Poster adapter. Real fixture verification: {capabilities?.poster.real_fixture_verified ? "complete" : "pending"}.</small></span></label></fieldset><label className="setup-dropzone"><Upload aria-hidden="true" /><strong>{file ? file.name : `Choose a ${formats} file`}</strong><small>{file ? `${formatBytes(file.size)} selected` : `Maximum ${formatBytes(capabilities?.spreadsheet.max_bytes ?? 10_485_760)}. Uploading does not change business data.`}</small><input type="file" accept={accepted} onChange={(event) => onFile(event.target.files?.[0] ?? null)} /></label>{inspection && <section className="setup-mapping"><div className="setup-section-heading"><div><h3>{inspection.mapping_required ? "Map your columns" : "File structure recognized"}</h3><p>Detected as {inspection.source_type.replaceAll("_", " ").toLowerCase()}. Mapping is stored with the import for audit and replay safety.</p></div></div><div className="setup-sheet-list">{inspection.sheets.map((sheet) => <span key={sheet.name}><strong>{sheet.name}</strong>{sheet.columns.length} columns</span>)}</div>{inspection.mapping_required && <><div className="setup-mapping-head"><span>Source column</span><span>Beanly field</span></div><div className="setup-mapping-list">{columns.map((column) => <label key={column}><span>{column}</span><select aria-label={`Map ${column}`} value={mapping[column] ?? ""} onChange={(event) => onMapping(column, event.target.value)}><option value="">Do not import</option>{GENERIC_IMPORT_COLUMNS.map((target) => <option key={target.value} value={target.value} disabled={selectedTargets.includes(target.value) && mapping[column] !== target.value}>{target.label}</option>)}</select></label>)}</div><p className="setup-mapping-note">Choose one profile: Menu requires Category, Product name, and Price. Inventory requires Inventory item name and Unit. Beanly never guesses a fuzzy column match.</p></>}</section>}<div className="setup-actions"><button className="setup-secondary" type="button" onClick={onBack}>Cancel</button><button className="setup-primary" type="submit" disabled={disabled || !file || !mappingReady}>{disabled ? <LoaderCircle className="is-spinning" /> : inspection ? <Upload /> : <FileSpreadsheet />}{inspection ? "Parse and review" : "Inspect columns"}</button></div></form>;
}

function RunView(props: { run: OnboardingImportRun; currency: string; working: boolean; canImport: boolean; canApply: boolean; targetDrafts: Record<string, string>; resolutionDrafts: Record<string, OnboardingImportResolution>; fieldDrafts: Record<string, string>; priceDrafts: Record<string, string>; reviewedRecipes: Set<string>; onBack: () => void; onTargetDraft: (id: string, value: string) => void; onFieldDraft: (id: string, value: string) => void; onPriceDraft: (id: string, value: string) => void; onReviewRecipe: (id: string, checked: boolean) => void; onResolution: (entity: OnboardingImportEntity, resolution: OnboardingImportResolution) => void; onSaveCorrection: (entity: OnboardingImportEntity) => void; onValidate: () => void; onSavePrices: () => void; onApply: () => void; onCancel: () => void; onResume: () => void; onActivate: () => void }) {
  const { run } = props;
  const counts = entityCounts(run);
  const priceEntities = run.entities.filter((entity) => ["VARIANT", "LOCATION_PRICE"].includes(entity.entity_type) && entity.resolution !== "SKIP");
  const recipes = run.entities.filter((entity) => entity.entity_type === "RECIPE" && entity.resolution !== "SKIP");
  const productIds = readyProductIds(run);
  const immutable = run.status === "APPLIED" || run.status === "CANCELLED";
  return <div className="setup-panel"><button className="setup-back" type="button" onClick={props.onBack}><ArrowLeft aria-hidden="true" />All setup options</button><div className="setup-run-heading"><div><p className="setup-eyebrow">Import preview</p><h2>{run.source_name}</h2><p>{run.file_name ?? `${run.source_type.replaceAll("_", " ").toLowerCase()} · version ${run.source_version ?? "current"}`}</p></div><span className={`setup-run-status is-${run.status.toLowerCase().replaceAll("_", "-")}`}>{IMPORT_STATUS_LABELS[run.status]}</span></div>{run.duplicate_warning && <div className="setup-warning"><AlertTriangle aria-hidden="true" /><span><strong>This file was imported before.</strong> Review the previous run before applying it again. Duplicate detection is a warning, not an automatic block.</span></div>}<div className="setup-summary-grid">{Object.entries(counts).map(([type, count]) => <article key={type}><span>{IMPORT_ENTITY_LABELS[type as keyof typeof IMPORT_ENTITY_LABELS]}</span><strong>{count}</strong></article>)}<article className={run.error_count ? "is-error" : ""}><span>Errors</span><strong>{run.error_count}</strong></article><article className={run.warning_count ? "is-warning" : ""}><span>Warnings</span><strong>{run.warning_count}</strong></article></div>

    {priceEntities.length > 0 && !immutable && <section className="setup-review-section"><div className="setup-section-heading"><div><h3>Set prices</h3><p>Enter customer-facing prices in {props.currency}. Decimals are supported when the currency requires them.</p></div></div><div className="setup-price-grid">{priceEntities.map((entity) => <label key={entity.id}><span>{entityDisplayName(entity)} · {props.currency}</span><input inputMode="decimal" value={props.priceDrafts[entity.id] ?? ""} onChange={(event) => props.onPriceDraft(entity.id, event.target.value)} /></label>)}</div><button className="setup-secondary" type="button" disabled={props.working || !props.canImport} onClick={props.onSavePrices}>Save prices</button></section>}

    <section className="setup-review-section"><div className="setup-section-heading"><div><h3>Review and resolve</h3><p>Exact matches may be linked. Fuzzy suggestions are never merged automatically.</p></div><span>{run.entity_count} entities</span></div><div className="setup-entity-list">{run.entities.map((entity) => { const field = editableField(entity); const resolution = props.resolutionDrafts[entity.id] ?? entity.resolution; return <article className={entity.error_codes.length ? "has-error" : entity.warning_codes.length ? "has-warning" : ""} key={entity.id}><div className="setup-entity-main"><span>{IMPORT_ENTITY_LABELS[entity.entity_type]}</span><strong>{entityDisplayName(entity)}</strong>{entityPayloadSummary(entity) && <small>{entityPayloadSummary(entity)}</small>}{entity.error_codes.length > 0 && <p className="is-error">{entity.error_codes.join(" · ")}</p>}{entity.warning_codes.length > 0 && <p className="is-warning">{entity.warning_codes.join(" · ")}</p>}</div>{!immutable && props.canImport && <div className="setup-entity-controls"><label><span>Resolution</span><select value={resolution} onChange={(event) => props.onResolution(entity, event.target.value as OnboardingImportResolution)}><option value="CREATE">Create</option><option value="MATCH_EXISTING">Match existing</option><option value="SKIP">Skip</option></select></label>{resolution === "MATCH_EXISTING" && <label><span>Confirmed target ID</span><input value={props.targetDrafts[entity.id] ?? entity.target_id ?? ""} onChange={(event) => props.onTargetDraft(entity.id, event.target.value)} /><button type="button" onClick={() => props.onResolution(entity, "MATCH_EXISTING")}>Save match</button></label>}{field && <label><span>Correct {field.label.toLowerCase()}</span><input value={props.fieldDrafts[entity.id] ?? ""} onChange={(event) => props.onFieldDraft(entity.id, event.target.value)} /><button type="button" onClick={() => props.onSaveCorrection(entity)}>Save correction</button></label>}</div>}</article>; })}</div></section>

    {recipes.length > 0 && <section className="setup-review-section"><div className="setup-section-heading"><div><h3>Review starter recipes</h3><p>These are draft starting values. Confirm each recipe only after checking quantities and inventory mappings.</p></div></div><div className="setup-recipe-list">{recipes.map((recipe) => <label key={recipe.id}><input type="checkbox" disabled={run.status !== "APPLIED" || !props.canApply} checked={props.reviewedRecipes.has(recipe.id)} onChange={(event) => props.onReviewRecipe(recipe.id, event.target.checked)} /><span><strong>{entityDisplayName(recipe)}</strong><small>{entityPayloadSummary(recipe) || "Review recipe components and quantities."}</small></span></label>)}</div></section>}

    {!props.canApply && !immutable && <div className="setup-warning"><AlertTriangle aria-hidden="true" /><span><strong>Preview-only access.</strong> Applying this run requires onboarding.write and menu.write, plus inventory.write when inventory, recipes, or opening balances are included.</span></div>}
    <div className="setup-actions setup-run-actions"><button className="setup-secondary" type="button" onClick={props.onBack}>Close</button>{run.status === "FAILED" && <button className="setup-secondary" type="button" disabled={props.working || !props.canImport} onClick={props.onResume}>Resume</button>}{!["APPLIED", "CANCELLED"].includes(run.status) && <button className="setup-danger" type="button" disabled={props.working || !props.canImport} onClick={props.onCancel}>Cancel import</button>}{!["APPLIED", "CANCELLED"].includes(run.status) && <button className="setup-secondary" type="button" disabled={props.working || !props.canImport} onClick={props.onValidate}>Validate</button>}{run.status === "READY" && <button className="setup-primary" type="button" disabled={props.working || !props.canApply || run.error_count > 0} onClick={props.onApply}>{props.working ? <LoaderCircle className="is-spinning" /> : <Check />}Apply atomically</button>}{run.status === "APPLIED" && productIds.length > 0 && <button className="setup-primary" type="button" disabled={props.working || !props.canApply || recipes.some((recipe) => !props.reviewedRecipes.has(recipe.id))} onClick={props.onActivate}>{props.working ? <LoaderCircle className="is-spinning" /> : <Check />}Activate {productIds.length} ready products</button>}</div>
  </div>;
}

function editableField(entity: OnboardingImportEntity) {
  const candidates = entity.entity_type === "VARIANT" ? ["variant_name", "name"] : entity.entity_type === "INVENTORY_ITEM" ? ["inventory_item_name", "name"] : entity.entity_type === "CATEGORY" ? ["category_name", "name"] : entity.entity_type === "PRODUCT" ? ["product_name", "name"] : [];
  const key = candidates.find((candidate) => candidate in entity.payload);
  return key ? { key, label: key.replaceAll("_", " ") } : null;
}

function replaceEntity(run: OnboardingImportRun, updated: OnboardingImportEntity): OnboardingImportRun {
  return { ...run, entities: run.entities.map((entity) => entity.id === updated.id ? updated : entity) };
}

function seedRunDrafts(run: OnboardingImportRun, setPrices: (value: Record<string, string>) => void, setFields: (value: Record<string, string>) => void) {
  setPrices(Object.fromEntries(run.entities.filter((entity) => ["VARIANT", "LOCATION_PRICE"].includes(entity.entity_type)).map((entity) => {
    const minor = typeof entity.payload.price_minor === "string" ? entity.payload.price_minor : String(entity.payload.price_minor ?? "");
    return [entity.id, /^\d+$/.test(minor) ? priceMinorToInput(minor) : ""];
  })));
  setFields(Object.fromEntries(run.entities.flatMap((entity) => { const field = editableField(entity); return field ? [[entity.id, String(entity.payload[field.key] ?? "")]] : []; })));
}

function errorMessage(caught: unknown, fallback: string) {
  if (caught instanceof ApiError && caught.code === "AI_EXTRACTION_UNAVAILABLE") return "AI Menu Import is unavailable because no extraction provider is configured.";
  return caught instanceof Error ? caught.message : fallback;
}
