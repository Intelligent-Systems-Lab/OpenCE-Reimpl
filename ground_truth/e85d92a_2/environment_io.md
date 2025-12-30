
### Environment Interaction 1
----------------------------------------------------------------------------
```python
# get supervisor's profile information.
apis.supervisor.show_profile()
```

```
Execution successful.
```


### Environment Interaction 2
----------------------------------------------------------------------------
```python
{
    account_password["account_name"]: account_password["password"]
    for account_password in apis.supervisor.show_account_passwords()
}
```

```
Execution successful.
```


### Environment Interaction 3
----------------------------------------------------------------------------
```python
search_results = apis.spotify.search_artists(query="Zoey James")
```

```
Execution successful.
```


### Environment Interaction 4
----------------------------------------------------------------------------
```python
artist_id = search_results[0]["artist_id"]
```

```
Execution successful.
```


### Environment Interaction 5
----------------------------------------------------------------------------
```python
sort_by = "+play_count"
```

```
Execution successful.
```


### Environment Interaction 6
----------------------------------------------------------------------------
```python
song = next(
    item
    for page_index in range(0, 10)
    for item in apis.spotify.search_songs(
        page_index=page_index, artist_id=artist_id, sort_by=sort_by
    )
)
```

```
Execution successful.
```


### Environment Interaction 7
----------------------------------------------------------------------------
```python
answer = song["title"]
```

```
Execution successful.
```


### Environment Interaction 8
----------------------------------------------------------------------------
```python
apis.supervisor.complete_task(status="success", answer=answer)
```

```
Execution successful.
```

