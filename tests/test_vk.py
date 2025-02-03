import os
import pytest
from escraper.parsers import VK

#######################################
## VK get_event
#######################################
def test_get_event():
    vk = VK()
    q = vk.get_event(event_url='https://vk.com/iwfyls_spb22')
    return(q)


#######################################
## VK token and VK id
#######################################
def test_token_in_args():
    assert "VK_TOKEN" in os.environ
    assert "VK_ID" in os.environ
    token = os.environ.get("TIMEPAD_TOKEN")
    VK(token)


def test_token_in_environ():
    assert "VK_TOKEN" in os.environ
    assert "VK_ID" in os.environ
    VK()
