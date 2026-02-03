import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getUserSettings, updateUserSettings, UserSettings } from "@dbsof/platform/userSettings";
import styles from "./settingsPage.module.scss";

export function SettingsPage() {
  const { instanceId } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const [settings, setSettings] = useState<UserSettings>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const serverUrl = "http://localhost:5757";
  const userId = "demo"; // For now, using demo user

  useEffect(() => {
    async function fetchSettings() {
      try {
        setLoading(true);
        setError(null);
        const fetchedSettings = await getUserSettings(serverUrl, userId);
        setSettings(fetchedSettings || {});
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load settings");
      } finally {
        setLoading(false);
      }
    }
    fetchSettings();
  }, []);

  const handleSave = async () => {
    try {
      setSaving(true);
      setSaveSuccess(false);
      setError(null);
      await updateUserSettings(serverUrl, userId, settings);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (key: string, value: any) => {
    setSettings({ ...settings, [key]: value });
  };

  if (loading) {
    return (
      <div className={styles.settingsPage}>
        <div className={styles.loading}>Loading settings...</div>
      </div>
    );
  }

  return (
    <div className={styles.settingsPage}>
      <div className={styles.header}>
        <h1>User Settings</h1>
        <button className={styles.backButton} onClick={() => navigate(-1)}>
          ← Back
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {saveSuccess && <div className={styles.success}>Settings saved successfully!</div>}

      <div className={styles.settingsForm}>
        {Object.keys(settings).length === 0 ? (
          <div className={styles.empty}>No settings configured yet.</div>
        ) : (
          Object.entries(settings).map(([key, value]) => (
            <div key={key} className={styles.settingRow}>
              <label className={styles.settingLabel}>{key}</label>
              <div className={styles.settingInput}>
                {typeof value === "boolean" ? (
                  <label className={styles.checkbox}>
                    <input
                      type="checkbox"
                      checked={value}
                      onChange={(e) => handleChange(key, e.target.checked)}
                    />
                    <span>{value ? "Enabled" : "Disabled"}</span>
                  </label>
                ) : typeof value === "number" ? (
                  <input
                    type="number"
                    value={value}
                    onChange={(e) => handleChange(key, Number(e.target.value))}
                  />
                ) : value === null ? (
                  <input
                    type="text"
                    value=""
                    placeholder="null"
                    onChange={(e) => handleChange(key, e.target.value || null)}
                  />
                ) : (
                  <input
                    type="text"
                    value={String(value)}
                    onChange={(e) => handleChange(key, e.target.value)}
                  />
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div className={styles.actions}>
        <button
          className={styles.saveButton}
          onClick={handleSave}
          disabled={saving || Object.keys(settings).length === 0}
        >
          {saving ? "Saving..." : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
