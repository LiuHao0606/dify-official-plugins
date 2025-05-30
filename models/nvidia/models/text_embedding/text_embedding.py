import time
from json import JSONDecodeError, dumps
from typing import Optional
from dify_plugin.entities.model import EmbeddingInputType, PriceType
from dify_plugin.entities.model.text_embedding import EmbeddingUsage, TextEmbeddingResult
from dify_plugin.errors.model import (
    CredentialsValidateFailedError,
    InvokeAuthorizationError,
    InvokeBadRequestError,
    InvokeConnectionError,
    InvokeError,
    InvokeRateLimitError,
    InvokeServerUnavailableError,
)
from dify_plugin.interfaces.model.text_embedding_model import TextEmbeddingModel

from requests import post


class NvidiaTextEmbeddingModel(TextEmbeddingModel):
    """
    Model class for Nvidia text embedding model.
    """

    api_base: str = "https://ai.api.nvidia.com/v1/retrieval/nvidia/embeddings"
    models: list[str] = ["NV-Embed-QA"]

    def _invoke(
        self,
        model: str,
        credentials: dict,
        texts: list[str],
        user: Optional[str] = None,
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> TextEmbeddingResult:
        """
        Invoke text embedding model

        :param model: model name
        :param credentials: model credentials
        :param texts: texts to embed
        :param user: unique user id
        :param input_type: input type
        :return: embeddings result
        """
        api_key = credentials["api_key"]
        if model not in self.models:
            raise InvokeBadRequestError("Invalid model name")
        if not api_key:
            raise CredentialsValidateFailedError("api_key is required")
        url = self.api_base
        headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
        data = {"model": model, "input": texts[0], "input_type": "query"}
        try:
            response = post(url, headers=headers, data=dumps(data))
        except Exception as e:
            raise InvokeConnectionError(str(e))
        if response.status_code != 200:
            try:
                resp = response.json()
                msg = resp["detail"]
                if response.status_code == 401:
                    raise InvokeAuthorizationError(msg)
                elif response.status_code == 429:
                    raise InvokeRateLimitError(msg)
                elif response.status_code == 500:
                    raise InvokeServerUnavailableError(msg)
                else:
                    raise InvokeError(msg)
            except JSONDecodeError as e:
                raise InvokeServerUnavailableError(
                    f"Failed to convert response to json: {e} with text: {response.text}"
                )
        try:
            resp = response.json()
            embeddings = resp["data"]
            usage = resp["usage"]
        except Exception as e:
            raise InvokeServerUnavailableError(f"Failed to convert response to json: {e} with text: {response.text}")
        usage = self._calc_response_usage(model=model, credentials=credentials, tokens=usage["total_tokens"])
        result = TextEmbeddingResult(
            model=model, embeddings=[[float(data) for data in x["embedding"]] for x in embeddings], usage=usage
        )
        return result

    def get_num_tokens(self, model: str, credentials: dict, texts: list[str]) -> list[int]:
        """
        Get number of tokens for given prompt messages

        :param model: model name
        :param credentials: model credentials
        :param texts: texts to embed
        :return:
        """
        if len(texts) == 0:
            return []
        total_num_tokens = []

        for text in texts:
            total_num_tokens.append(self._get_num_tokens_by_gpt2(text))
        return total_num_tokens

    def validate_credentials(self, model: str, credentials: dict) -> None:
        """
        Validate model credentials

        :param model: model name
        :param credentials: model credentials
        :return:
        """
        try:
            self._invoke(model=model, credentials=credentials, texts=["ping"])
        except InvokeAuthorizationError:
            raise CredentialsValidateFailedError("Invalid api key")

    @property
    def _invoke_error_mapping(self) -> dict[type[InvokeError], list[type[Exception]]]:
        return {
            InvokeConnectionError: [InvokeConnectionError],
            InvokeServerUnavailableError: [InvokeServerUnavailableError],
            InvokeRateLimitError: [InvokeRateLimitError],
            InvokeAuthorizationError: [InvokeAuthorizationError],
            InvokeBadRequestError: [KeyError],
        }

    def _calc_response_usage(self, model: str, credentials: dict, tokens: int) -> EmbeddingUsage:
        """
        Calculate response usage

        :param model: model name
        :param credentials: model credentials
        :param tokens: input tokens
        :return: usage
        """
        input_price_info = self.get_price(
            model=model, credentials=credentials, price_type=PriceType.INPUT, tokens=tokens
        )
        usage = EmbeddingUsage(
            tokens=tokens,
            total_tokens=tokens,
            unit_price=input_price_info.unit_price,
            price_unit=input_price_info.unit,
            total_price=input_price_info.total_amount,
            currency=input_price_info.currency,
            latency=time.perf_counter() - self.started_at,
        )
        return usage
