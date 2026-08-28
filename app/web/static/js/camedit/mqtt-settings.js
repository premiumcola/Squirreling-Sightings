// ─── camedit/mqtt-settings.js ──────────────────────────────────────────────
// The MQTT block of the global Settings panel — hydrate + save + status
// badge. Extracted from camedit/index.js, which was already 550 lines
// past the 400-line ceiling before this pass added the secret-field
// contract to it; the broker section is a self-contained sub-concern
// with exactly one input set and one save button, so it is the cleanest
// seam available.
//
// The broker password follows the same three-state contract as the
// Telegram token and the RTSP password — see chrome/secret-field.js.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { showToast } from '../core/toast.js';
import { apiPost } from '../core/api.js';
import { loadAll } from '../live-update.js';
import { hydrateSecretField, applySecretField } from '../chrome/secret-field.js';

export function hydrateMqttSettings() {
  const mqtt = state.config?.mqtt || {};
  const mqttEn = byId('mqtt_enabled');
  if (mqttEn) mqttEn.checked = !!mqtt.enabled;
  const mqttH = byId('mqtt_host');
  if (mqttH) mqttH.value = mqtt.host || '';
  const mqttP = byId('mqtt_port');
  if (mqttP) mqttP.value = mqtt.port || 1883;
  const mqttU = byId('mqtt_username');
  if (mqttU) mqttU.value = mqtt.username || '';
  // The server ships mqtt.password_set, never the password.
  hydrateSecretField(byId('mqtt_password'), mqtt.password_set, 'Passwort');
  const mqttT = byId('mqtt_base_topic');
  if (mqttT) mqttT.value = mqtt.base_topic || 'tam-spy';
  const mqttBadge = byId('mqttStatusBadge');
  if (mqttBadge) {
    mqttBadge.textContent = mqtt.enabled ? 'aktiv' : 'aus';
    mqttBadge.className =
      'set-status-badge ' + (mqtt.enabled ? 'set-status-badge--on' : 'set-status-badge--off');
  }
}

export async function saveMqttSettings() {
  const mqtt = {
    enabled: byId('mqtt_enabled')?.checked || false,
    host: byId('mqtt_host')?.value || '',
    port: Number(byId('mqtt_port')?.value || 1883),
    username: byId('mqtt_username')?.value || '',
    base_topic: byId('mqtt_base_topic')?.value || 'tam-spy',
  };
  // Omitted → keep stored · "" → clear · value → replace.
  applySecretField(mqtt, 'password', byId('mqtt_password'));
  await apiPost('/api/settings/app', { mqtt });
  showToast('MQTT gespeichert · Verbindungen werden neu gestartet.', 'success');
  await loadAll();
}

// data-action="saveMqttSettings" in settings.html resolves through the
// action-registry shim, which looks the handler up by window name.
window.saveMqttSettings = saveMqttSettings;
