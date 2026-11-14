//! Player preferences that clients keep the same on every device. Each key holds one value and
//! the time it was chosen; the newest choice wins, key by key, so two devices changing different
//! settings keep both changes.
//!
//! The keys and their types are defined once, in `tests/fixtures/synced_settings.json`, which
//! both clients test against too.

use crate::access::require_owner;
use crate::app::{App, now_ms};
use crate::store::Error;
use crate::web_util::store_error;
use axum::extract::{DefaultBodyLimit, Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::get;
use axum::{Json, Router};
use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::sync::{Arc, OnceLock};

const PATH: &str = "/api/settings/{user}";

/// Ten keys with their times fit in well under a kilobyte.
const BODY_LIMIT: usize = 8192;

const SCHEMA: &str = include_str!("../tests/fixtures/synced_settings.json");

/// What values a key accepts.
#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum Kind {
    Bool,
    Int { min: i64, max: i64 },
}

impl Kind {
    fn accepts(&self, value: &Value) -> bool {
        match self {
            Kind::Bool => value.is_boolean(),
            Kind::Int { min, max } => value.as_i64().is_some_and(|n| (*min..=*max).contains(&n)),
        }
    }
}

#[derive(Debug, Deserialize)]
struct Key {
    key: String,
    #[serde(flatten)]
    kind: Kind,
}

#[derive(Deserialize)]
struct Schema {
    keys: Vec<Key>,
}

/// The known keys by name, read once from the shared fixture.
fn keys() -> &'static BTreeMap<String, Kind> {
    static KEYS: OnceLock<BTreeMap<String, Kind>> = OnceLock::new();
    KEYS.get_or_init(|| {
        let schema: Schema =
            serde_json::from_str(SCHEMA).expect("tests/fixtures/synced_settings.json is valid");
        schema
            .keys
            .into_iter()
            .map(|key| (key.key, key.kind))
            .collect()
    })
}

/// One setting's value and when the player chose it, in milliseconds since the epoch.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub(crate) struct Entry {
    value: Value,
    updated_at: i64,
}

pub fn initialize(conn: &Connection) -> Result<(), Error> {
    conn.execute_batch(
        "create table if not exists synced_settings (
             user text not null,
             key text not null,
             value text not null,
             updated_at integer not null,
             primary key (user, key)
         ) without rowid;",
    )?;
    Ok(())
}

/// The player's stored settings. Rows a key no longer accepts are left out.
fn load(conn: &Connection, user: &str) -> Result<BTreeMap<String, Entry>, Error> {
    let mut stmt =
        conn.prepare("select key, value, updated_at from synced_settings where user = ?1")?;
    let rows = stmt.query_map([user], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, i64>(2)?,
        ))
    })?;
    let mut found = BTreeMap::new();
    for row in rows {
        let (key, text, updated_at) = row?;
        let Ok(value) = serde_json::from_str::<Value>(&text) else {
            continue;
        };
        if keys().get(&key).is_some_and(|kind| kind.accepts(&value)) {
            found.insert(key, Entry { value, updated_at });
        }
    }
    Ok(found)
}

/// A change split into the entries to merge, with future times moved to `now`, and the unknown
/// keys. None when a known key has a value it does not accept or a negative time.
fn checked(
    incoming: BTreeMap<String, Entry>,
    now: i64,
) -> Option<(BTreeMap<String, Entry>, Vec<String>)> {
    let mut known = BTreeMap::new();
    let mut ignored = Vec::new();
    for (key, entry) in incoming {
        let Some(kind) = keys().get(&key) else {
            ignored.push(key);
            continue;
        };
        if !kind.accepts(&entry.value) || entry.updated_at < 0 {
            return None;
        }
        let updated_at = entry.updated_at.min(now);
        known.insert(
            key,
            Entry {
                value: entry.value,
                updated_at,
            },
        );
    }
    Some((known, ignored))
}

/// Stores each entry newer than the one stored; an equally old one keeps the stored value.
fn merge(conn: &Connection, user: &str, entries: &BTreeMap<String, Entry>) -> Result<(), Error> {
    let transaction = conn.unchecked_transaction()?;
    for (key, entry) in entries {
        transaction.execute(
            "insert into synced_settings (user, key, value, updated_at) values (?1, ?2, ?3, ?4)
             on conflict (user, key) do update set value = excluded.value, updated_at = excluded.updated_at
             where excluded.updated_at > synced_settings.updated_at",
            params![user, key, entry.value.to_string(), entry.updated_at],
        )?;
    }
    transaction.commit()?;
    Ok(())
}

#[derive(Debug, Serialize)]
struct Settings {
    settings: BTreeMap<String, Entry>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Change {
    settings: BTreeMap<String, Entry>,
}

/// The merged settings after a change, and the keys this server does not know.
#[derive(Debug, Serialize)]
struct Merged {
    settings: BTreeMap<String, Entry>,
    ignored: Vec<String>,
}

async fn get_settings(
    State(app): State<Arc<App>>,
    Path(user): Path<String>,
    headers: HeaderMap,
) -> Result<Json<Settings>, StatusCode> {
    require_owner(&app, &user, &headers)?;
    let store = app.store.lock().unwrap();
    let settings = load(&store.conn, &user).map_err(store_error)?;
    Ok(Json(Settings { settings }))
}

async fn put_settings(
    State(app): State<Arc<App>>,
    Path(user): Path<String>,
    headers: HeaderMap,
    Json(change): Json<Change>,
) -> Result<Json<Merged>, StatusCode> {
    require_owner(&app, &user, &headers)?;
    let (entries, ignored) = checked(change.settings, now_ms()).ok_or(StatusCode::BAD_REQUEST)?;
    let store = app.store.lock().unwrap();
    merge(&store.conn, &user, &entries).map_err(store_error)?;
    let settings = load(&store.conn, &user).map_err(store_error)?;
    Ok(Json(Merged { settings, ignored }))
}

pub(crate) fn routes() -> Router<Arc<App>> {
    Router::new().route(
        PATH,
        get(get_settings)
            .put(put_settings)
            .layer(DefaultBodyLimit::max(BODY_LIMIT)),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::*;
    use axum::extract::Path as UrlPath;

    #[derive(Deserialize)]
    struct Fixture {
        server_merge: Vec<Case>,
    }

    #[derive(Deserialize)]
    struct Case {
        name: String,
        now_ms: i64,
        stored: BTreeMap<String, Entry>,
        incoming: BTreeMap<String, Entry>,
        #[serde(default)]
        expected: BTreeMap<String, Entry>,
        #[serde(default)]
        ignored: Vec<String>,
        #[serde(default)]
        refused: bool,
    }

    fn entry(value: Value, updated_at: i64) -> Entry {
        Entry { value, updated_at }
    }

    #[test]
    fn the_shared_fixture_names_every_key_once_with_a_valid_default() {
        let fixture: Value = serde_json::from_str(SCHEMA).unwrap();
        let listed = fixture["keys"].as_array().unwrap();
        assert_eq!(listed.len(), keys().len(), "keys are unique");
        for key in listed {
            let name = key["key"].as_str().unwrap();
            assert!(keys()[name].accepts(&key["default"]), "{name} default");
            assert!(
                name.bytes().all(|b| b.is_ascii_lowercase() || b == b'_'),
                "{name} is snake_case"
            );
        }
    }

    #[test]
    fn merges_follow_the_shared_cases() {
        let fixture: Fixture = serde_json::from_str(SCHEMA).unwrap();
        for case in fixture.server_merge {
            let (store, path) = temporary_store();
            merge(&store.conn, "hill", &case.stored).unwrap();
            match checked(case.incoming, case.now_ms) {
                None => assert!(case.refused, "{}: refused", case.name),
                Some((entries, ignored)) => {
                    assert!(!case.refused, "{}: accepted", case.name);
                    merge(&store.conn, "hill", &entries).unwrap();
                    assert_eq!(
                        load(&store.conn, "hill").unwrap(),
                        case.expected,
                        "{}",
                        case.name
                    );
                    assert_eq!(ignored, case.ignored, "{}", case.name);
                }
            }
            cleanup(store, path);
        }
    }

    #[test]
    fn rows_a_key_no_longer_accepts_are_left_out() {
        let (store, path) = temporary_store();
        store
            .conn
            .execute_batch(
                "insert into synced_settings values ('hill', 'retired', 'true', 1);
                 insert into synced_settings values ('hill', 'notify_rank', '3', 1);
                 insert into synced_settings values ('hill', 'deck_status', 'false', 1);",
            )
            .unwrap();
        assert_eq!(
            load(&store.conn, "hill").unwrap(),
            BTreeMap::from([("deck_status".into(), entry(false.into(), 1))])
        );
        cleanup(store, path);
    }

    #[tokio::test]
    async fn settings_are_private_and_kept_for_each_player() {
        let (app, path) = fixture();
        let put = |user: &str, token: &str, settings: Value| {
            put_settings(
                State(app.clone()),
                UrlPath(user.into()),
                headers(token),
                Json(serde_json::from_value(serde_json::json!({ "settings": settings })).unwrap()),
            )
        };
        assert_eq!(
            put("hill", "cerro", serde_json::json!({})).await.err(),
            Some(StatusCode::UNAUTHORIZED)
        );
        assert_eq!(
            get_settings(State(app.clone()), UrlPath("hill".into()), headers("cerro"))
                .await
                .err(),
            Some(StatusCode::UNAUTHORIZED)
        );
        assert_eq!(
            put(
                "hill",
                "hill",
                serde_json::json!({"notify_rank": {"value": 1, "updated_at": 5}})
            )
            .await
            .err(),
            Some(StatusCode::BAD_REQUEST)
        );
        let merged = put(
            "hill",
            "hill",
            serde_json::json!({
                "notify_rank": {"value": false, "updated_at": 5},
                "later": {"value": true, "updated_at": 5}
            }),
        )
        .await
        .unwrap()
        .0;
        assert_eq!(merged.ignored, ["later"]);
        assert_eq!(
            merged.settings,
            BTreeMap::from([("notify_rank".into(), entry(false.into(), 5))])
        );
        let read =
            |user: &str| get_settings(State(app.clone()), UrlPath(user.into()), headers(user));
        assert_eq!(read("hill").await.unwrap().0.settings, merged.settings);
        assert!(read("cerro").await.unwrap().0.settings.is_empty());
        cleanup(app, path);
    }
}
