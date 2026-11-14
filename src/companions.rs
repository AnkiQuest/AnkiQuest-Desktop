//! A player's visual study companion, shared by the website and installed clients.
use crate::access::require_owner;
use crate::{
    App,
    store::{Error, Store},
};
use axum::{
    Json,
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

pub const DEFAULT: &str = "aki";

/// The hidden companion a player finds in the companion picker.
pub(crate) const COW: &str = "cow";

/// Every stored companion. Keep [`TABLE`]'s check in step; changing it needs a migration step.
const COMPANIONS: [&str; 4] = ["aki", "ankilope", COW, "none"];

pub(crate) const TABLE: &str = "create table if not exists companion_preferences (
    user text primary key,
    companion text not null check (companion in ('aki', 'ankilope', 'cow', 'none'))
) without rowid;";

pub fn valid(value: &str) -> bool {
    COMPANIONS.contains(&value)
}

/// Something a player unlocks once and keeps. Unlocks are not settings: settings sync does not
/// touch them.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Unlock {
    /// The cow companion, found by tapping Ankilope in the picker.
    Cow,
}

impl Unlock {
    const ALL: [Unlock; 1] = [Unlock::Cow];

    pub(crate) fn id(self) -> &'static str {
        match self {
            Unlock::Cow => "cow",
        }
    }

    fn parse(id: &str) -> Option<Unlock> {
        Self::ALL.into_iter().find(|unlock| unlock.id() == id)
    }
}

/// The unlock `companion` needs before a player may choose it.
fn needed(companion: &str) -> Option<Unlock> {
    (companion == COW).then_some(Unlock::Cow)
}

/// Whose art draws `companion`. The cow has no art yet (#88), so it borrows Ankilope's, which
/// `cards::cow_art` tints purple.
pub(crate) fn art_owner(companion: &str) -> &str {
    if companion == COW {
        "ankilope"
    } else {
        companion
    }
}

pub fn initialize(conn: &Connection) -> Result<(), Error> {
    conn.execute_batch(TABLE)?;
    conn.execute_batch(
        "create table if not exists companion_unlocks (
            user text not null,
            unlock text not null,
            unlocked_at integer not null,
            primary key (user, unlock)
        ) without rowid;",
    )?;
    Ok(())
}

impl Store {
    pub fn companion(&self, user: &str) -> Result<String, Error> {
        Ok(self
            .conn
            .query_row(
                "select companion from companion_preferences where user = ?1",
                [user],
                |row| row.get(0),
            )
            .optional()?
            .unwrap_or_else(|| DEFAULT.into()))
    }

    pub fn set_companion(&self, user: &str, companion: &str) -> Result<(), Error> {
        self.conn.execute(
            "insert into companion_preferences (user, companion) values (?1, ?2)
             on conflict (user) do update set companion = excluded.companion",
            params![user, companion],
        )?;
        Ok(())
    }

    /// What `user` has unlocked, in [`Unlock::ALL`]'s order. Ids this server no longer knows
    /// are left out.
    pub(crate) fn unlocks(&self, user: &str) -> Result<Vec<Unlock>, Error> {
        let mut stmt = self
            .conn
            .prepare("select unlock from companion_unlocks where user = ?1")?;
        let ids: Vec<String> = stmt
            .query_map([user], |row| row.get(0))?
            .collect::<Result<_, _>>()?;
        Ok(Unlock::ALL
            .into_iter()
            .filter(|unlock| ids.iter().any(|id| id == unlock.id()))
            .collect())
    }

    /// Records `unlock` for `user`; unlocking again keeps the first time.
    pub(crate) fn add_unlock(&self, user: &str, unlock: Unlock, at_ms: i64) -> Result<(), Error> {
        self.conn.execute(
            "insert into companion_unlocks (user, unlock, unlocked_at) values (?1, ?2, ?3)
             on conflict (user, unlock) do nothing",
            params![user, unlock.id(), at_ms],
        )?;
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Preference {
    pub companion: String,
}

pub async fn get(
    State(app): State<Arc<App>>,
    Path(user): Path<String>,
    headers: HeaderMap,
) -> Result<Json<Preference>, StatusCode> {
    require_owner(&app, &user, &headers)?;
    let companion = app
        .store
        .lock()
        .unwrap()
        .companion(&user)
        .map_err(crate::store_error)?;
    Ok(Json(Preference { companion }))
}

pub async fn set(
    State(app): State<Arc<App>>,
    Path(user): Path<String>,
    headers: HeaderMap,
    Json(preference): Json<Preference>,
) -> Result<Json<Preference>, StatusCode> {
    require_owner(&app, &user, &headers)?;
    if !valid(&preference.companion) {
        return Err(StatusCode::BAD_REQUEST);
    }
    let store = app.store.lock().unwrap();

    // A hidden companion stays hidden until the player has unlocked it.
    if let Some(unlock) = needed(&preference.companion) {
        let unlocks = store.unlocks(&user).map_err(crate::store_error)?;
        if !unlocks.contains(&unlock) {
            return Err(StatusCode::CONFLICT);
        }
    }
    store
        .set_companion(&user, &preference.companion)
        .map_err(crate::store_error)?;
    Ok(Json(preference))
}

#[derive(Serialize)]
pub struct Unlocks {
    unlocks: Vec<&'static str>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UnlockRequest {
    unlock: String,
}

fn unlocks_of(store: &Store, user: &str) -> Result<Json<Unlocks>, StatusCode> {
    let unlocks = store.unlocks(user).map_err(crate::store_error)?;
    Ok(Json(Unlocks {
        unlocks: unlocks.into_iter().map(Unlock::id).collect(),
    }))
}

pub async fn get_unlocks(
    State(app): State<Arc<App>>,
    Path(user): Path<String>,
    headers: HeaderMap,
) -> Result<Json<Unlocks>, StatusCode> {
    require_owner(&app, &user, &headers)?;
    unlocks_of(&app.store.lock().unwrap(), &user)
}

pub async fn add_unlock(
    State(app): State<Arc<App>>,
    Path(user): Path<String>,
    headers: HeaderMap,
    Json(request): Json<UnlockRequest>,
) -> Result<Json<Unlocks>, StatusCode> {
    require_owner(&app, &user, &headers)?;
    let unlock = Unlock::parse(&request.unlock).ok_or(StatusCode::BAD_REQUEST)?;
    let store = app.store.lock().unwrap();
    store
        .add_unlock(&user, unlock, crate::app::now_ms())
        .map_err(crate::store_error)?;
    unlocks_of(&store, &user)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn choice_is_per_player_and_survives_reopening_the_store() {
        let (store, path) = crate::test_support::temporary_store();
        assert_eq!(store.companion("alice").unwrap(), DEFAULT);
        store.set_companion("alice", "ankilope").unwrap();
        store.set_companion("bob", "none").unwrap();
        drop(store);
        let reopened = Store::open(&path).unwrap();
        assert_eq!(reopened.companion("alice").unwrap(), "ankilope");
        assert_eq!(reopened.companion("bob").unwrap(), "none");
        assert_eq!(reopened.companion("carol").unwrap(), DEFAULT);
    }

    #[test]
    fn unlocks_are_per_player_kept_once_and_survive_reopening_the_store() {
        let (store, path) = crate::test_support::temporary_store();
        assert!(store.unlocks("alice").unwrap().is_empty());
        store.add_unlock("alice", Unlock::Cow, 1).unwrap();
        store.add_unlock("alice", Unlock::Cow, 2).unwrap();
        drop(store);
        let reopened = Store::open(&path).unwrap();
        assert_eq!(reopened.unlocks("alice").unwrap(), [Unlock::Cow]);
        assert!(reopened.unlocks("bob").unwrap().is_empty());
        let first: i64 = reopened
            .conn
            .query_row("select unlocked_at from companion_unlocks", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(first, 1, "unlocking again keeps the first time");
    }

    #[test]
    fn every_companion_fits_the_table_and_only_the_cow_needs_an_unlock() {
        let (store, _path) = crate::test_support::temporary_store();
        for companion in COMPANIONS {
            store.set_companion("alice", companion).unwrap();
            assert_eq!(store.companion("alice").unwrap(), companion);
            assert_eq!(needed(companion).is_some(), companion == COW, "{companion}");
        }
        assert!(store.set_companion("alice", "unknown").is_err());
        assert_eq!(art_owner(COW), "ankilope");
        assert_eq!(art_owner("aki"), "aki");
        for unlock in Unlock::ALL {
            assert_eq!(Unlock::parse(unlock.id()), Some(unlock));
        }
        assert_eq!(Unlock::parse("Cow"), None);
    }

    #[tokio::test]
    async fn the_cow_is_unlocked_by_its_owner_once_and_only_then_chosen() {
        use crate::test_support::{call, cleanup, fixture};
        use serde_json::{Value, json};

        let (app, path) = fixture();
        let unlocks = "/api/unlocks/hill";
        let companion = "/api/companion/hill";
        let cow = json!({"companion": "cow"});

        // Nothing is unlocked yet, so the cow cannot be chosen.
        let nothing = json!({"unlocks": []});
        let got = call(&app, "GET", unlocks, "hill-secret", Value::Null).await;
        assert_eq!(got, (StatusCode::OK, nothing));
        let refused = call(&app, "POST", companion, "hill-secret", cow.clone()).await;
        assert_eq!(refused.0, StatusCode::CONFLICT);

        // Only the player's own token unlocks, and only known ids.
        let unlock = json!({"unlock": "cow"});
        let other = call(&app, "POST", unlocks, "cerro-secret", unlock.clone()).await;
        assert_eq!(other.0, StatusCode::UNAUTHORIZED);
        let other = call(&app, "GET", unlocks, "cerro-secret", Value::Null).await;
        assert_eq!(other.0, StatusCode::UNAUTHORIZED);
        let unknown = json!({"unlock": "horse"});
        let bad = call(&app, "POST", unlocks, "hill-secret", unknown).await;
        assert_eq!(bad.0, StatusCode::BAD_REQUEST);

        // Unlocking twice answers the same list; then the cow can be chosen.
        let unlocked = (StatusCode::OK, json!({"unlocks": ["cow"]}));
        for _ in 0..2 {
            let answer = call(&app, "POST", unlocks, "hill-secret", unlock.clone()).await;
            assert_eq!(answer, unlocked);
        }
        let got = call(&app, "GET", unlocks, "hill-secret", Value::Null).await;
        assert_eq!(got, unlocked);
        let chosen = call(&app, "POST", companion, "hill-secret", cow.clone()).await;
        assert_eq!(chosen, (StatusCode::OK, cow.clone()));
        let got = call(&app, "GET", companion, "hill-secret", Value::Null).await;
        assert_eq!(got, (StatusCode::OK, cow.clone()));

        // Another player's unlock is their own.
        let theirs = "/api/companion/cerro";
        let refused = call(&app, "POST", theirs, "cerro-secret", cow).await;
        assert_eq!(refused.0, StatusCode::CONFLICT);
        cleanup(app, path);
    }
}
