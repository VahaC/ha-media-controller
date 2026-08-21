@service
async def sync_ma_queue(
    entity_id="media_player.jbl_bar_91_true_2",
    window_before=5,
    window_size=50
):
    """Fetch only a small window around current MA queue item and store as sensor."""

    import json

    window_before = int(window_before)
    window_size = int(window_size)

    # ---------------------------------------------------------
    # 1. Get current queue position first
    # ---------------------------------------------------------
    queue_info = await hass.services.async_call(
        "music_assistant",
        "get_queue",
        {
            "entity_id": entity_id
        },
        blocking=True,
        return_response=True,
    )

    if not queue_info or entity_id not in queue_info:
        log.error("No queue info returned")
        return

    raw_current_index = queue_info[entity_id].get("current_index", -1)

    try:
        current_index = int(raw_current_index)
    except (TypeError, ValueError):
        current_index = -1

    # ---------------------------------------------------------
    # 2. Calculate a window around the current item
    #
    # Example:
    # global current_index = 537
    # offset = 532
    #
    # ESP receives items 532..581
    # local current_index = 5
    # ---------------------------------------------------------
    if current_index >= 0:
        offset = max(current_index - window_before, 0)
    else:
        offset = 0

    # ---------------------------------------------------------
    # 3. Fetch ONLY window_size queue items
    # ---------------------------------------------------------
    result = await hass.services.async_call(
        "mass_queue",
        "get_queue_items",
        {
            "entity": entity_id,
            "offset": offset,
            "limit": window_size,
        },
        blocking=True,
        return_response=True,
    )

    if not result or entity_id not in result:
        log.error("No queue data returned")
        return

    items = result[entity_id]

    titles = [item.get("media_title", "") for item in items]
    artists = [item.get("media_artist", "") for item in items]
    queue_ids = [item.get("queue_item_id", "") for item in items]

    # ---------------------------------------------------------
    # 4. Convert global MA index to index inside our small window
    # ---------------------------------------------------------
    if current_index >= 0:
        local_current_index = current_index - offset
    else:
        local_current_index = 0

    if items:
        local_current_index = max(
            0,
            min(local_current_index, len(items) - 1)
        )
    else:
        local_current_index = 0

    log.info(
        f"Queue window: "
        f"items={len(items)}, "
        f"global_index={current_index}, "
        f"offset={offset}, "
        f"local_index={local_current_index}"
    )

    # ---------------------------------------------------------
    # 5. ESP32 receives only the small window
    # ---------------------------------------------------------
    data_str = json.dumps(
        {
            "titles": titles,
            "artists": artists,
            "queue_ids": queue_ids,
            "current_index": local_current_index,
            "count": len(titles),
        },
        ensure_ascii=False,
    )

    hass.states.async_set(
        "sensor.ma_queue_json",
        "ok",
        {
            "data": data_str,
            "count": len(titles),
        }
    )

    log.info(
        f"sensor.ma_queue_json updated with {len(titles)} queue items"
    )