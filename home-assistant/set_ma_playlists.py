@service
async def sync_ma_playlists(config_entry_id=None, limit=50):
    """Fetch playlists from Music Assistant and store as sensor."""
    
    if config_entry_id is None:
        log.error("config_entry_id is required")
        return
    
    # -- Call Music Assistant get_library action --
    result = await hass.services.async_call(
        "music_assistant",
        "get_library",
        {
            "config_entry_id": config_entry_id,
            "media_type": "playlist",
            "limit": limit,
        },
        blocking=True,
        return_response=True,
    )
    
    if not result or "items" not in result:
        log.error("No items in MA response")
        return
    
    items = result["items"]
    # -- Filter out auto-generated library playlists --
    items = [item for item in items if "(from library)" not in item.get("name", "")]
    names = [item.get("name", "") for item in items]
    uris = [item.get("uri", "") for item in items]
    
    log.info(f"Fetched {len(names)} playlists from Music Assistant")
    
    # -- Store as sensor with names and uris as attributes --
    hass.states.async_set(
        "sensor.ma_playlists_json",
        "ok",
        {
            "names": names,
            "uris": uris,
            "count": len(names),
        }
    )
    
    log.info(f"sensor.ma_playlists_json updated with {len(names)} playlists")