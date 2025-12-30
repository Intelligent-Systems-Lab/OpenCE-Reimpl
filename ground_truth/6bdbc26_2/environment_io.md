
### Environment Interaction 1
----------------------------------------------------------------------------
```python
# get supervisor's profile information.
supervisor_profile = apis.supervisor.show_profile()
```

```
Execution successful.
```


### Environment Interaction 2
----------------------------------------------------------------------------
```python
supervisor_passwords = {
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
access_token = apis.spotify.login(
    username=supervisor_profile["email"], password=supervisor_passwords["spotify"]
)["access_token"]
```

```
Execution successful.
```


### Environment Interaction 4
----------------------------------------------------------------------------
```python
current_song = apis.spotify.show_current_song(access_token=access_token)
```

```
Execution successful.
```


### Environment Interaction 5
----------------------------------------------------------------------------
```python
artist_id = current_song["artists"][0]["id"]
```

```
Execution successful.
```


### Environment Interaction 6
----------------------------------------------------------------------------
```python
artist = apis.spotify.show_artist(artist_id=artist_id)
```

```
Execution successful.
```


### Environment Interaction 7
----------------------------------------------------------------------------
```python
answer = artist["follower_count"]
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

